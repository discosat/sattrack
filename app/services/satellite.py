import os
from datetime import datetime, timezone, timedelta
from skyfield.api import load, wgs84
from skyfield.iokit import parse_tle_file
from pydantic import BaseModel

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "../config")
TLE_FILE_PATH = os.path.join(CONFIG_DIR, "disco.tle")

class Pass(BaseModel):
    # Times are in UTC
    rise: datetime
    culminate: datetime
    set: datetime
    
    def to_dict(self):
        """Convert Pass object to dictionary for JSON serialization"""
        return {
            "rise": self.rise.isoformat(),
            "culminate": self.culminate.isoformat(),
            "set": self.set.isoformat()
        }
    
    def __lt__(self, other):
        """For priority queue comparison"""
        return self.rise < other.rise

class Satellite:
    def __init__(self, gs_logger):
        self.gs_logger = gs_logger
        self.ts = load.timescale()
        self.satellite_name = None
        self.satellite = None
        self.location = self._load_gs_location()
        
        # Load the satellite
        self.load_satellite()
        
    def _load_gs_location(self):
        """Load location from file or use default"""
        try:
            location_file = os.path.join(CONFIG_DIR, "location.txt")
            with open(location_file, "r") as file:
                lines = file.readlines()
                latitude = float(lines[0].strip())
                longitude = float(lines[1].strip())
                self.gs_logger.info(f"Loaded location: {latitude}, {longitude}")
        except (FileNotFoundError, IndexError, ValueError):
            # Default location (Aarhus)
            latitude = 56.162937
            longitude = 10.203921
            self.gs_logger.info(f"Using default location: {latitude}, {longitude}")
        
        return wgs84.latlon(latitude, longitude)
    
    def load_satellite(self) -> bool:
        """Load the satellite from its TLE file"""        
        # Check if file exists
        if not os.path.exists(TLE_FILE_PATH):
            self.gs_logger.error(f"TLE file not found")
            return False
        
        try:
            with load.open(TLE_FILE_PATH) as f:
                satellites = list(parse_tle_file(f, self.ts))
            
            if not satellites:
                self.gs_logger.error(f"No satellites found in TLE file")
                return False
            
            self.satellite = satellites[0]
            self.satellite_name = self.satellite.name
            self.gs_logger.info(f"Loaded satellite: {self.satellite_name}")
            return True
        except Exception as e:
            self.gs_logger.error(f"Error loading satellite: {str(e)}")
            return False
    
    def get_sat_position(self) -> dict:
        """Get current latitude and longitude of the satellite"""
        if not self.satellite:
            return None
        
        # Get current position
        t = self.ts.now()
        geocentric = self.satellite.at(t)
        
        subpoint = geocentric.subpoint()
        
        return {
            "satellite": self.satellite_name,
            "latitude": subpoint.latitude.degrees,
            "longitude": subpoint.longitude.degrees,
            "elevation": subpoint.elevation.m,
            "timestamp": t.utc_datetime().isoformat()
        }
    
    def get_passes(self, start_time=None, end_time=None, min_elevation=5.0) -> list[Pass]:
        """Get passes for the satellite in a given time frame"""
        if not self.satellite:
            return []
        
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        
        if end_time is None:
            end_time = start_time + timedelta(days=1)
        
        return self._get_passes(start_time, end_time, min_elevation)
    
    def _get_passes(self, start: datetime, end: datetime, deg: float=5.0) -> list[Pass]:
        """
        Get the passes for the satellite in a given time frame
        Args:
            start: datetime object (UTC)
            end: datetime object (UTC)
            deg: minimum elevation in degrees
        Returns:
            list of passes
        """
        acc = []
        t, events = self.satellite.find_events(self.location, self.ts.from_datetime(start), 
                                   self.ts.from_datetime(end), altitude_degrees=deg)
        
        for i in range(0, len(events), 3):
            if i+2 < len(events) and events[i] == 0 and events[i+1] == 1 and events[i+2] == 2:
                acc.append(Pass(rise=t[i].utc_datetime(), 
                               culminate=t[i+1].utc_datetime(),
                               set=t[i+2].utc_datetime()))
        return acc
    
    def get_next_pass(self, min_elevation: float=5.0, start_date: datetime = None) -> Pass:
        """Get the next pass for the satellite"""
        if not self.satellite:
            return None
        
        return self._get_next_pass(min_elevation, start_date)
    
    def _get_next_pass(self, deg: float=10.0, start_date: datetime = None) -> Pass:
        """
        Get the next pass for the satellite
        Args:
            deg: minimum elevation in degrees
            start_date: The date to start the search from. UTC time shall be provided
        Returns:
            Pass object
        """
        if start_date is None:
            start = self.ts.now()
        else:
            start = self.ts.from_datetime(start_date)
            
        t, events = self.satellite.find_events(self.location, start, start + 1, altitude_degrees=deg)
        
        # If no events or incomplete pass, search further
        attempts = 0
        max_attempts = 10  # Limit search to prevent infinite loop
        
        while attempts < max_attempts:
            if len(events) >= 3 and events[0] == 0 and events[1] == 1 and events[2] == 2:
                return Pass(rise=t[0].utc_datetime(), 
                           culminate=t[1].utc_datetime(),
                           set=t[2].utc_datetime())
            
            # Search further ahead
            if len(events) > 0:
                start = t[-1] + 0.1  # Add a little time to avoid same events
            else:
                start = start + 1  # Add a day if no events found
                
            t, events = self.satellite.find_events(self.location, start, start + 1, altitude_degrees=deg)
            attempts += 1
        
        self.gs_logger.warning(f"Could not find next pass after {max_attempts} attempts")
        return None
