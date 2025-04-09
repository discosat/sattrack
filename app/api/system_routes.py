from fastapi import APIRouter, Depends, HTTPException
from skyfield.api import wgs84
from api.dependencies import get_tracker

system_router = APIRouter()

@system_router.get('/location')
async def get_location(tracker = Depends(get_tracker)):
    """Get the current observer location"""
    location = tracker.satellite.location
    return {
        "latitude": location.latitude.degrees,
        "longitude": location.longitude.degrees
    }

@system_router.post('/location')
async def set_location(
    latitude: float,
    longitude: float,
    tracker = Depends(get_tracker)
):
    """Set the observer location"""
    try:
        # Update the location file
        with open("location.txt", "w") as f:
            f.write(f"{latitude}\n{longitude}\n")
        # Update the tracker's location
        tracker.satellite.location = wgs84.latlon(latitude, longitude)
        
        return {
            "success": True,
            "latitude": latitude,
            "longitude": longitude
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
