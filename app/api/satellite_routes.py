from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
from skyfield.api import wgs84
from api.dependencies import get_tracker
from pydantic import BaseModel
satellite_router = APIRouter()

@satellite_router.get('')
async def get_satellite_info(tracker = Depends(get_tracker)):
    """Get information about the tracked satellite"""
    return {
        "name": tracker.satellite_name,
        "tracking": tracker.is_tracking,
        "status": tracker.tracking_data["status"]
    }

@satellite_router.get('/position')
async def get_satellite_position(tracker = Depends(get_tracker)):
    """Get current position of the satellite"""
    position = tracker.satellite.get_sat_position()
    if position:
        return position
    raise HTTPException(status_code=404, detail="Satellite position not available")

@satellite_router.get('/passes')
async def get_satellite_passes(
    days: int = 1,
    min_elevation: float = 10.0,
    tracker = Depends(get_tracker)
):
    """Get passes for the satellite in a given time frame"""
    if days < 1:
        raise HTTPException(status_code=400, detail="Days must be greater than 0")
    if min_elevation < 5:
        raise HTTPException(status_code=400, detail="Minimum elevation must be greater than 5")    
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(days=days)

    passes = tracker.satellite.get_passes(start_time, end_time, min_elevation=min_elevation)
    return [p.to_dict() for p in passes]

@satellite_router.get('/next-pass')
async def get_next_pass(
    min_elevation: float = 10.0,
    tracker = Depends(get_tracker)    
):
    """Get the next pass for the satellite""" 
    if min_elevation < 5:
        raise HTTPException(status_code=400, detail="Minimum elevation must be greater than 5")   
    next_pass = tracker.satellite.get_next_pass(min_elevation=min_elevation)
    if next_pass is None:
        raise HTTPException(status_code=404, detail="No upcoming passes found")

    return next_pass.to_dict()

@satellite_router.post('/reload')
async def reload_sat_tle(tracker = Depends(get_tracker)):
    """Reload the starfield satellite object with fresh tle data."""
    success = tracker.reload_satellite()
    return {"success": success}

@satellite_router.get('/track/data')
async def get_tracking_data(tracker = Depends(get_tracker)):
    """Get the latest tracking data"""
    data = tracker.get_tracking_data()
    return data

@satellite_router.post('/track/schedule')
async def schedule_pass(rise: str, tracker = Depends(get_tracker)):
    """Rise must be given in UTC and in ISO format. Finds next available pass from given rise"""
    try:
        rise_date = datetime.fromisoformat(rise)
        rise_date = rise_date.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format, use ISO format")
    
    success = tracker.schedule_pass(rise_date)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to schedule pass. Check for overlap or time constraints")
    
    return {"message": "Pass scheduled successfully", "success": success}

@satellite_router.post('/track/cancel/pass')
async def cancel_pass(rise: str, tracker = Depends(get_tracker)):
    success = tracker.cancel_pass(rise)
    if not success:
        raise HTTPException(status_code=404, detail="Pass not found or already completed")
    return {"message": "Pass cancelled successfully"}

@satellite_router.post('/track/cancel/all')
async def cancel_all_passes(tracker = Depends(get_tracker)):
    """Cancel all scheduled passes"""
    tracker.stop_scheduler()
    # Restart the scheduler
    tracker._start_scheduler()
    
    return {"message": "All passes cancelled successfully"}
