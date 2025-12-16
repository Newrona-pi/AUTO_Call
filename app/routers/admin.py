from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import csv
import io
from ..database import get_db
from .. import models, schemas

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)

# --- Scenarios ---
@router.post("/scenarios/", response_model=schemas.Scenario)
def create_scenario(scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    db_scenario = models.Scenario(**scenario.dict())
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario

@router.put("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def update_scenario(scenario_id: int, scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    for key, value in scenario.dict().items():
        setattr(db_scenario, key, value)
    
    db.commit()
    db.refresh(db_scenario)
    return db_scenario

@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    db.query(models.Question).filter(models.Question.scenario_id == scenario_id).delete()
    db.delete(db_scenario)
    db.commit()
    return {"message": "Scenario deleted"}

@router.get("/scenarios/", response_model=List[schemas.Scenario])
def read_scenarios(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(models.Scenario).offset(skip).limit(limit).all()

@router.get("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def read_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()
    if db_scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return db_scenario

# --- Questions ---
@router.post("/questions/", response_model=schemas.Question)
def create_question(question: schemas.QuestionCreate, db: Session = Depends(get_db)):
    db_question = models.Question(**question.dict())
    db.add(db_question)
    db.commit()
    db.refresh(db_question)
    return db_question

@router.put("/questions/{question_id}", response_model=schemas.Question)
def update_question(question_id: int, question_update: schemas.QuestionBase, db: Session = Depends(get_db)):
    db_question = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db_question.text = question_update.text
    db_question.sort_order = question_update.sort_order
    db_question.is_active = question_update.is_active
    
    db.commit()
    db.refresh(db_question)
    return db_question

@router.delete("/questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    db_question = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db.delete(db_question)
    db.commit()
    return {"message": "Question deleted"}

@router.get("/scenarios/{scenario_id}/questions", response_model=List[schemas.Question])
def read_questions_by_scenario(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.Question).filter(
        models.Question.scenario_id == scenario_id
    ).order_by(models.Question.sort_order).all()

# --- Phone Numbers ---
@router.post("/phone_numbers/", response_model=schemas.PhoneNumber)
def create_or_update_phone_number(phone: schemas.PhoneNumberCreate, db: Session = Depends(get_db)):
    # Normalize: ensure + prefix
    to_number = phone.to_number.strip()
    if not to_number.startswith('+'):
        to_number = '+' + to_number
    
    db_phone = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == to_number).first()
    if db_phone:
        db_phone.scenario_id = phone.scenario_id
        db_phone.label = phone.label
        db_phone.is_active = phone.is_active
    else:
        db_phone = models.PhoneNumber(
            to_number=to_number,
            scenario_id=phone.scenario_id,
            label=phone.label,
            is_active=phone.is_active
        )
        db.add(db_phone)
    db.commit()
    db.refresh(db_phone)
    return db_phone

@router.delete("/phone_numbers/{to_number}")
def delete_phone_number(to_number: str, db: Session = Depends(get_db)):
    db_phone = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == to_number).first()
    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")
    db.delete(db_phone)
    db.commit()
    return {"message": "Phone number deleted"}

@router.get("/phone_numbers/", response_model=List[schemas.PhoneNumber])
def read_phone_numbers(db: Session = Depends(get_db)):
    return db.query(models.PhoneNumber).all()

# --- Logs & Stats ---
@router.get("/calls/", response_model=List[schemas.CallLog])
def read_calls(
    skip: int = 0, 
    limit: int = 100, 
    to_number: Optional[str] = None, 
    from_number: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Call).options(joinedload(models.Call.answers).joinedload(models.Answer.question))
    
    if to_number:
        query = query.filter(models.Call.to_number == to_number)
    if from_number:
        query = query.filter(models.Call.from_number == from_number)
        
    calls = query.order_by(models.Call.started_at.desc()).offset(skip).limit(limit).all()
    return calls 

@router.get("/export_csv")
def export_calls_csv(
    to_number: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Call).options(joinedload(models.Call.answers).joinedload(models.Answer.question))
    
    if to_number:
        query = query.filter(models.Call.to_number == to_number)
    
    calls = query.order_by(models.Call.started_at.desc()).all()
    
    stream = io.StringIO()
    writer = csv.writer(stream)
    
    writer.writerow(["CallSid", "Date", "To", "From", "ScenarioID", "Question", "AnswerType", "RecordingURL", "Transcript"])
    
    for call in calls:
        scenario_id = call.scenario_id if call.scenario_id else ""
        
        if not call.answers:
            writer.writerow([
                call.call_sid, call.started_at, call.to_number, call.from_number, 
                scenario_id, "", "", "", ""
            ])
        else:
            for ans in call.answers:
                q_text = ans.question.text if ans.question else "Unknown"
                writer.writerow([
                    call.call_sid, call.started_at, call.to_number, call.from_number,
                    scenario_id, q_text, ans.answer_type, 
                    ans.recording_url_twilio or "", 
                    ans.transcript_text or ""
                ])
                
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=export.csv"
    return response

# --- Frontend Render ---
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard")
def dashboard_ui(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})
