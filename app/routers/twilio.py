from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse
from ..database import get_db
from .. import models
import os
import requests
from openai import OpenAI

router = APIRouter(
    prefix="/twilio",
    tags=["twilio"],
)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

async def transcribe_with_whisper(answer_id: int, recording_url: str, recording_sid: str):
    """Transcribe audio using OpenAI Whisper API"""
    import time
    
    try:
        if not OPENAI_API_KEY:
            print("OpenAI API key not configured")
            return
        
        # Download audio from Twilio with retry logic
        audio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
        
        max_retries = 5
        retry_delay = 2  # seconds
        audio_response = None
        
        for attempt in range(max_retries):
            audio_response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            
            if audio_response.status_code == 200:
                break
            
            if attempt < max_retries - 1:
                print(f"Recording not ready yet (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Failed to download recording after {max_retries} attempts: {recording_sid}")
                return
        
        # Save temporarily
        temp_file = f"/tmp/{recording_sid}.mp3"
        with open(temp_file, 'wb') as f:
            f.write(audio_response.content)
            
        audio_bytes = os.path.getsize(temp_file)
        
        # Transcribe with Whisper
        start_time = time.time()
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(temp_file, 'rb') as audio_file:
            # Use verbose_json to get duration
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja",
                response_format="verbose_json"
            )
        processing_time = time.time() - start_time
        
        transcript_text = transcript.text
        audio_duration = getattr(transcript, 'duration', 0)
        
        # Update database
        from ..database import SessionLocal
        db = SessionLocal()
        # Phase 2: Guard with recording_sid check to prevent mismatch
        answer = db.query(models.Answer).filter(
            models.Answer.id == answer_id,
            models.Answer.recording_sid == recording_sid
        ).first()
        
        if answer:
            answer.transcript_text = transcript_text
            answer.transcript_status = "completed"
            
            # Log success with Phase 2 details
            log_entry = models.TranscriptionLog(
                answer_id=answer_id,
                service="openai_whisper",
                status="success",
                audio_bytes=audio_bytes,
                audio_duration=int(audio_duration),
                model_name="whisper-1",
                language="ja",
                request_payload=f"file={recording_sid}.mp3",
                response_payload=transcript_text[:1000] if transcript_text else "",
                processing_time=int(processing_time)
            )
            db.add(log_entry)
            
            db.commit()
        else:
            print(f"Warning: Answer mismatch or not found for id={answer_id}, sid={recording_sid}")

        db.close()
        
        # Clean up
        if os.path.exists(temp_file):
            os.remove(temp_file)
        print(f"Transcription completed for {recording_sid}: {transcript_text}")
        
    except Exception as e:
        print(f"Transcription error for {recording_sid}: {str(e)}")
        # Update status to failed and log
        from ..database import SessionLocal
        db = SessionLocal()
        answer = db.query(models.Answer).filter(
            models.Answer.id == answer_id,
            models.Answer.recording_sid == recording_sid
        ).first()
        
        if answer:
            answer.transcript_status = "failed"
            
            # Log failure
            log_entry = models.TranscriptionLog(
                answer_id=answer_id,
                service="openai_whisper",
                status="failed",
                audio_bytes=audio_bytes if 'audio_bytes' in locals() else 0,
                model_name="whisper-1",
                request_payload=f"file={recording_sid}.mp3",
                response_payload=str(e),
                processing_time=0
            )
            db.add(log_entry)
            
            db.commit()
        db.close()
        
        # Clean up
        temp_file = f"/tmp/{recording_sid}.mp3"
        if os.path.exists(temp_file):
            os.remove(temp_file)

async def transcribe_message_with_whisper(message_id: int, recording_url: str, recording_sid: str):
    """Transcribe Message audio using OpenAI Whisper API"""
    import time
    
    try:
        if not OPENAI_API_KEY: return
        
        # Download audio from Twilio with retry logic
        audio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
        
        max_retries = 5
        retry_delay = 2
        audio_response = None
        
        for attempt in range(max_retries):
            audio_response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            if audio_response.status_code == 200: break
            time.sleep(retry_delay)
            retry_delay *= 2
        
        if not audio_response or audio_response.status_code != 200:
            print(f"Failed to download message recording: {recording_sid}")
            return

        temp_file = f"/tmp/msg_{recording_sid}.mp3"
        with open(temp_file, 'wb') as f:
            f.write(audio_response.content)
            
        # Transcribe
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(temp_file, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )
        
        # Update DB
        from ..database import SessionLocal
        db = SessionLocal()
        msg = db.query(models.Message).filter(models.Message.id == message_id).first()
        if msg:
            msg.transcript_text = transcript.text
            db.commit()
        db.close()
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
    except Exception as e:
        print(f"Message transcription error: {e}")
        # Clean up
        temp_file = f"/tmp/msg_{recording_sid}.mp3"
        if os.path.exists(temp_file):
            os.remove(temp_file)

@router.post("/voice")
async def handle_incoming_call(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    db: Session = Depends(get_db)
):
    from twilio.rest import Client
    
    # Normalize phone number
    def normalize_phone(number):
        normalized = number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not normalized.startswith('+'):
            normalized = '+' + normalized
        return normalized
    
    to_normalized = normalize_phone(To)
    
    # 1. Lookup Scenario
    phone_entry = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == To).first()
    if not phone_entry:
        all_numbers = db.query(models.PhoneNumber).all()
        for pn in all_numbers:
            if normalize_phone(pn.to_number) == to_normalized:
                phone_entry = pn
                break
    
    # Create Call record (initial)
    call = models.Call(
        call_sid=CallSid,
        from_number=From,
        to_number=To,
        status="in-progress",
        scenario_id=phone_entry.scenario_id if phone_entry else None
    )
    
    # 2. Start Full Call Recording
    recording_sid = None
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            # Create a recording for the call (in-progress)
            # Twilio API: POST /2010-04-01/Accounts/{AccountSid}/Calls/{CallSid}/Recordings.json
            rec = client.calls(CallSid).recordings.create()
            recording_sid = rec.sid
            call.recording_sid = recording_sid
        except Exception as e:
            print(f"Failed to start full call recording: {e}")

    db.add(call)
    db.commit()

    vr = VoiceResponse()

    if not phone_entry or not phone_entry.scenario.is_active:
        vr.say("現在この番号は使われておりません。", language="ja-JP")
        return Response(content=str(vr), media_type="application/xml")

    scenario = phone_entry.scenario

    # 3. Greeting
    if scenario.greeting_text:
        vr.say(scenario.greeting_text, language="ja-JP")
    
    if scenario.disclaimer_text:
        vr.say(scenario.disclaimer_text, language="ja-JP")

    # 4. Question Guidance
    guidance_text = scenario.question_guidance_text or "このあと何点か質問をさせていただきます。回答が済みましたらシャープを押して次に進んでください"
    vr.say(guidance_text, language="ja-JP")
    vr.pause(length=1.5)

    # 5. Ask First Question
    first_question = db.query(models.Question).filter(
        models.Question.scenario_id == scenario.id,
        models.Question.is_active == True
    ).order_by(models.Question.sort_order).first()

    if first_question:
        vr.say(first_question.text, language="ja-JP")
        action_url = f"/twilio/record_callback?scenario_id={scenario.id}&q_curr={first_question.id}"
        vr.record(
            action=action_url, 
            finish_on_key="#",
            timeout=0,
            max_length=180 # 3 minutes
        )
    else:
        # Check for Ending Guidance if no questions?
        ending_guidances = db.query(models.EndingGuidance).filter(
            models.EndingGuidance.scenario_id == scenario.id
        ).order_by(models.EndingGuidance.sort_order).all()
        
        if ending_guidances:
             for eg in ending_guidances:
                 vr.say(eg.text, language="ja-JP")
                 vr.pause(length=1)
        else:
            vr.say("終了します。", language="ja-JP")
            
    return Response(content=str(vr), media_type="application/xml")

@router.post("/record_callback")
async def handle_recording(
    request: Request,
    scenario_id: int,
    q_curr: int, 
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # Get current question for sort_order
    current_q = db.query(models.Question).get(q_curr)
    
    # 1. Save Answer
    answer = models.Answer(
        call_sid=CallSid,
        question_id=q_curr,
        answer_type="recording",
        recording_sid=RecordingSid,
        recording_url_twilio=RecordingUrl,
        transcript_status="processing",
        question_sort_at_call=current_q.sort_order if current_q else 0
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)
    
    # 2. Transcribe (async)
    import asyncio
    asyncio.create_task(transcribe_with_whisper(answer.id, RecordingUrl, RecordingSid))

    vr = VoiceResponse()

    # 3. Find Next Question
    if not current_q:
        vr.say("エラーが発生しました。", language="ja-JP")
        return Response(content=str(vr), media_type="application/xml")

    next_question = db.query(models.Question).filter(
        models.Question.scenario_id == scenario_id,
        models.Question.is_active == True,
        models.Question.sort_order > current_q.sort_order
    ).order_by(models.Question.sort_order).first()

    if next_question:
        # Ask next
        vr.say(next_question.text, language="ja-JP")
        action_url = f"/twilio/record_callback?scenario_id={scenario_id}&q_curr={next_question.id}"
        vr.record(
            action=action_url, 
            finish_on_key="#",
            timeout=0,
            max_length=180
        )
    else:
        # Phase 4: Message Recording
        vr.say("担当者に伝えたいことがあればお話しください。終わったらシャープを押してください。", language="ja-JP")
        vr.record(
            action=f"/twilio/message_record?scenario_id={scenario_id}",
            finish_on_key="#",
            timeout=10,
            max_length=180
        )
            
    return Response(content=str(vr), media_type="application/xml")

@router.post("/message_record")
async def handle_message_recording(
    request: Request,
    scenario_id: int,
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # Save Message
    msg = models.Message(
        call_sid=CallSid,
        recording_sid=RecordingSid,
        recording_url=RecordingUrl,
        transcript_text="(文字起こし中...)"
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    
    # Async transcribe
    import asyncio
    asyncio.create_task(transcribe_message_with_whisper(msg.id, RecordingUrl, RecordingSid))
    
    vr = VoiceResponse()
    vr.say("録音を受け付けました。", language="ja-JP")
    
    # Confirm
    from twilio.twiml.voice_response import Gather
    gather = Gather(num_digits=1, action=f"/twilio/message_confirm?scenario_id={scenario_id}", timeout=10)
    gather.say("他にお話しすることはありますか？ ある場合は、1を。終わる場合は、2、またはそのままお待ちください。", language="ja-JP")
    vr.append(gather)
    
    # If no input, default to end (2)
    vr.redirect(f"/twilio/message_confirm?scenario_id={scenario_id}&Digits=2")
    
    return Response(content=str(vr), media_type="application/xml")

@router.post("/message_confirm")
async def handle_message_confirm(
    request: Request,
    scenario_id: int,
    Digits: str = Form("2"),
    db: Session = Depends(get_db)
):
    vr = VoiceResponse()
    
    if Digits == "1":
        # Retry recording
        vr.say("担当者に伝えたいことがあればお話しください。終わったらシャープを押してください。", language="ja-JP")
        vr.record(
            action=f"/twilio/message_record?scenario_id={scenario_id}",
            finish_on_key="#",
            timeout=10,
            max_length=180
        )
        return Response(content=str(vr), media_type="application/xml")
    
    # End
    ending_guidances = db.query(models.EndingGuidance).filter(
        models.EndingGuidance.scenario_id == scenario_id
    ).order_by(models.EndingGuidance.sort_order).all()
    
    if ending_guidances:
        for eg in ending_guidances:
            vr.say(eg.text, language="ja-JP")
            vr.pause(length=1)
    else:
        vr.say("お問い合わせありがとうございました。", language="ja-JP")
        
    vr.say("失礼いたします。", language="ja-JP")
    vr.hangup()
    
    return Response(content=str(vr), media_type="application/xml")

# Keep transcription_callback for safety/legacy? Or remove? 
# The user wants Whisper, so native transcription is likely disabled or ignored.
# We will keep it but it does nothing if we don't enable it in vr.record parameters (transcribe=True is default false).
@router.post("/transcription_callback")
async def handle_transcription(
    request: Request,
    TranscriptionText: str = Form(None),
    RecordingSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # Log native Twilio transcription if it ever comes
    print(f"Native transcription Rx for {RecordingSid}: {TranscriptionText}")
    return Response(content="OK", media_type="text/plain")
