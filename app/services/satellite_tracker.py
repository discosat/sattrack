"""
Assumes that only one satellite is in tle file. If there are multiple it will take the first one
"""

import threading
import os
from datetime import datetime, timezone, timedelta
from skyfield.api import load, wgs84
from skyfield.iokit import parse_tle_file
from pydantic import BaseModel
import subprocess
from services.rotor_controller import RotorController

from queue import PriorityQueue

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

class SatelliteTracker:
    def __init__(self, gs_logger):
        self.gs_logger = gs_logger
        self.gs_logger.info("Initializing satellite tracker")
        self.tle_file = "disco.tle"
        self.ts = load.timescale()

        self.satellite_name = None
        self.satellite = None
        self.is_tracking = False
        self.tracking_thread = None
        self.stop_tracking_event = threading.Event()
        
        # Default location (can be overridden)
        self.location = self._load_gs_location()

        # Tracking data
        self.tracking_data = {
            "azimuth": 0,
            "elevation": 0,
            "distance": 0,
            "last_updated": None,
            "status": "idle",  # idle, waiting or tracking
            "current_pass": None
        }
        
        # Load the satellite
        self.load_satellite()
        
        # Load stuff for scheduler
        self.scheduled_passes = PriorityQueue()
        self.scheduler_thread = None
        self.is_scheduler_running = False
        self.scheduler_stop_event = threading.Event()
        self.current_scheduled_pass = None
        self.scheduler_lock = threading.Lock()       

    async def _async_init(self):
        self.rotor = await RotorController.initialize()
    
    def _load_gs_location(self):
        """Load location from file or use default"""
        try:
            with open("location.txt", "r") as file:
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
            self.gs_logger.error(f"Error loading satellite {self.satellite_name}: {str(e)}")
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
    
    def get_next_pass(self, min_elevation: float=5.0) -> Pass:
        """Get the next pass for the satellite"""
        if not self.satellite:
            return None
        
        return self._get_next_pass(min_elevation)
    
    def _get_next_pass(self, deg: float=10.0, start_date: datetime = None) -> Pass:
        """
        Get the next pass for the satellite
        Args:
            deg: minimum elevation in degrees
            start_date: The date to start the search from. UTC time shall be provided
        Returns:
            Pass object
        """
        start = self.ts.from_datetime(start_date) or self.ts.now()
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
        
     
    def start_tracking(self, start_date: datetime = None):
        """Start tracking the satellite"""
        if self.is_tracking:
            return False
        
        if not self.satellite:
            if not self.load_satellite():
                return False
        # Clear previous stop signal
        self.stop_tracking_event.clear()

        # Find the next pass
        next_pass = self._get_next_pass(deg=10.0, start_date=start_date)
        if not next_pass:
            self.gs_logger.error(f"No upcoming passes found for {self.satellite_name}")
            return False
        
        # Update tracking data
        self.tracking_data["status"] = "waiting"
        self.tracking_data["current_pass"] = next_pass
    


        # Start tracking thread
        self.tracking_thread = threading.Thread(
            target=self._track_satellite,
            args=(next_pass,)
        )
        self.tracking_thread.daemon = True
        self.tracking_thread.start()
        
        self.is_tracking = True
        self.gs_logger.info(f"Started tracking {self.satellite_name}, next pass at {next_pass.rise}")
        return True
    
    async def _track_satellite(self, sat_pass):
        """Track the satellite during a pass"""
        # Sleep till the rise time
        now = datetime.now(timezone.utc)
        time_till_rise = (sat_pass.rise - now).total_seconds()
        
        if time_till_rise > 0:
            self.gs_logger.info(f"Waiting until rise time for {self.satellite_name}: {sat_pass.rise}")
            self.tracking_data["status"] = "waiting"
            if self.stop_tracking_event.wait(timeout=time_till_rise):
                self.gs_logger.info(f"Tracking canceled before rise time for {self.satellite_name}")
                self.tracking_data["status"] = "idle"
                self.is_tracking = False
                return

            # Sleep until rise time
            # threading.Event().wait(time_till_rise)
        
        # Update status
        self.tracking_data["status"] = "tracking"
        
        # Track the satellite during the pass
        while self.is_tracking:
            now = datetime.now(timezone.utc)
            
            # Check if the pass is over
            if now > sat_pass.set:
                self.gs_logger.info(f"Pass completed for {self.satellite_name}")
                break
            
            # Calculate position
            difference = self.satellite - self.location
            topocentric = difference.at(self.ts.now())
            alt, az, distance = topocentric.altaz()
            
            # Send azimuth, elevation to rotctl
            # subprocess.run(["rotctl", "P", az.degrees, alt.degrees])
            await self.rotor.write(az.degrees, alt.degrees)

            
            self.gs_logger.info(f"Setting azimuth: {az.degrees}, elevation: {alt.degrees}")

            # Update tracking data
            self.tracking_data.update({
                "azimuth": az.degrees,
                "elevation": alt.degrees,
                "distance": distance.km,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })
            
            # If below horizon, stop tracking
            if alt.degrees < 0:
                self.gs_logger.info(f"Satellite {self.satellite_name} below horizon, stopping tracking")
                break
                
            if self.stop_tracking_event.wait(timeout=1):
                break
        # Update status
        self.tracking_data["status"] = "idle"
        self.is_tracking = False
    
    def stop_tracking(self):
        """Stop tracking the satellite"""
        if not self.is_tracking:
            return False

        self.stop_tracking_event.set()
        
        if self.tracking_thread and self.tracking_thread.is_alive():
            self.tracking_thread.join(timeout=2.0)  # Wait up to 2 seconds for thread to finish

        self.is_tracking = False
        self.tracking_data["status"] = "idle"
        self.tracking_data["current_pass"] = None
        self.gs_logger.info(f"Stopped tracking satellite {self.satellite_name}")
        return True
    
    def get_tracking_data(self):
        """Get the latest tracking data"""
        return {
            "satellite": self.satellite_name,
            "azimuth": self.tracking_data["azimuth"],
            "elevation": self.tracking_data["elevation"],
            "distance": self.tracking_data["distance"],
            "status": self.tracking_data["status"],
            "last_updated": self.tracking_data["last_updated"],
            "pass": self.tracking_data["current_pass"].to_dict() if self.tracking_data["current_pass"] else None
        }
    
    def reload_satellite(self):
        """Reload the satellite. This should be done when there is a fresh TLE"""
        if self.is_tracking:
            self.gs_logger.error("Cannot reload satellite while GS is tracking")
            return False
        return self.load_satellite()

    def start_scheduler(self):
        if self.is_scheduler_running:
            return False
        
        self.scheduler_stop_event.clear()
        self.is_scheduler_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        self.gs_logger.info("Pass scheduler started")
        return True

    def stop_scheduler(self):
        if not self.is_scheduler_running:
            return False

        self.scheduler_stop_event.set()

        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=2.0)
        
        if self.is_tracking:
            self.stop_tracking()
        
        self.is_scheduler_running = False
        self.gs_logger.info("Pass scheduler stopped")
        return True

    def schedule_pass(self, pass: Pass):
        with self.scheduler_lock:
            now = datetieme.now
            if pass.rise <= now:
                self.gs_logger.error("Cannot schedule a pass that has already started")
                return False

            one_week_later = now + timedelta(days=7)
            if pass.rise > one_week_later:
                self.gs_logger.error("Cannot schedule a pass that starts a week from now")
                return False

            if self._is_overlapping(pass):
                self.gs_logger.error("Cannot schedule a pass that is overlapping another pass")
                return False
            
            self.scheduled_passes.put((pass_obj.rise, pass_obj))
            self.gs_logger.info(f"Scheduled pass for {self.satellite_name} at {pass_obj.rise}")
            return True

    def _is_overlapping(self, new_pass):
        """ Check if passes are overlapping with other passes """
        if self.tracking and self.tracking_data["current_pass"]:
            current_pass = self.tracking_data["current_pass"]
            # Is this really the right checks?
            if new_pass.rise < current_pass.set and new_pass.set > current_pass.rise:
                return True
            if new_pass.rise > current_pass.rise and new_pass.rise < current_pass.set:
                return True

        tmp_q = PriorityQueue()
        has_overlap = False

        while not self.schedueled_pass.empty()
            priority, pass = self.schedueled_pass.get()
            # Right checks?
            if new_pass.rise < pass.set and new_pass.set > pass.rise:
                has_overlap = True
            if new_pass.rise > pass.rise and new_pass.rise < pass.set:
                has_overlap = True

            tmp_q.put((priority, pass))

        # Restore the priority queue
        while not tmp_q.empty():
            self.schedueled_passes.put(tmp_q.get())
        return has_overlap
