import threading
import asyncio
from datetime import datetime, timezone, timedelta
import os
from queue import PriorityQueue
from typing import Optional, List
import json
from services.rotor_controller import RotorController
from services.satellite import Satellite, Pass

PERSISTENCE_FOLDER = os.path.join(os.path.dirname(__file__), "../persistence") 

class SatelliteTracker:
    def __init__(self, gs_logger):
        self.gs_logger = gs_logger
        self.gs_logger.info("Initializing satellite tracker")
        
        # Tracking state
        self.is_tracking = False
        self.tracking_thread = None
        self.track_stop_event = threading.Event()
        self.lock = threading.RLock()
        
        # Scheduling state
        self.scheduled_passes = PriorityQueue()
        self.scheduler_thread = None
        self.scheduler_stop_event = threading.Event()
        self.is_scheduling = False
        
        # Tracking data
        self.tracking_data = {
            "azimuth": 0,
            "elevation": 0,
            "distance": 0,
            "last_updated": None,
            "status": "idle",  # idle, waiting, tracking
            "current_pass": None,
            "scheduled_passes": []
        }

        self.rotor = None
        self.satellite = Satellite(gs_logger)
        self.satellite_name = self.satellite.satellite_name
        
        # Start the scheduler immediately
        self._start_scheduler()
    
    async def _async_init(self):
        """Asynchronous initialization for the rotor controller"""
        self.rotor = await RotorController.initialize()
        return self
    
    @classmethod
    async def initialize(cls, gs_logger):
        """Factory method for creating and initializing the tracker"""
        tracker = cls(gs_logger)
        return await tracker._async_init()
    
    def reload_satellite(self):
        """Reload the satellite TLE data"""
        with self.lock:
            if self.is_tracking:
                self.gs_logger.error("Cannot reload satellite while tracking")
                return False
                
            return self.satellite.load_satellite()
    
    def _can_schedule_pass(self, pass_to_schedule: Pass) -> bool:
        """
        Check if a pass can be scheduled based on constraints:
        - Not more than a week from now
        - Not overlapping with existing scheduled passes
        """
        # Check if pass is in the future
        now = datetime.now(timezone.utc)
        
        # Check if pass has already ended
        if pass_to_schedule.set < now:
            self.gs_logger.error("Cannot schedule a pass that has already ended")
            return False
            
        # Check if pass is more than a week away
        one_week_from_now = now + timedelta(days=7)
        if pass_to_schedule.rise > one_week_from_now:
            self.gs_logger.error("Cannot schedule passes more than a week in advance")
            return False
            
        # Check for overlap with existing scheduled passes
        # Get a copy of all passes without emptying the queue
        temp_queue = PriorityQueue()
        has_overlap = False
        
        while not self.scheduled_passes.empty():
            existing_pass = self.scheduled_passes.get()
            temp_queue.put(existing_pass)
            
            # Check for overlap
            # Pass overlaps if:
            # - New pass rise time is between existing pass rise and set
            # - New pass set time is between existing pass rise and set
            # - New pass completely contains existing pass
            if ((existing_pass.rise <= pass_to_schedule.rise <= existing_pass.set) or
                (existing_pass.rise <= pass_to_schedule.set <= existing_pass.set) or
                (pass_to_schedule.rise <= existing_pass.rise and pass_to_schedule.set >= existing_pass.set)):
                has_overlap = True
        
        # Restore the queue
        while not temp_queue.empty():
            self.scheduled_passes.put(temp_queue.get())
            
        if has_overlap:
            self.gs_logger.error("Cannot schedule overlapping passes")
            return False
            
        return True
    
    def _correct_pass(self, pass_to_correct: datetime) -> Pass:
        return self.satellite.get_next_pass(start_date=pass_to_correct)

    def schedule_pass(self, pass_to_schedule_rise: datetime) -> bool:
        """Schedule a specific satellite pass for tracking"""
        with self.lock:
            # We should correct the given pass to an actual pass from the satellite
            pass_to_schedule = self._correct_pass(pass_to_schedule_rise)

            # Check if pass is valid according to constraints
            if not self._can_schedule_pass(pass_to_schedule):
                return False
                
            # Add to priority queue
            self.scheduled_passes.put(pass_to_schedule)
            
            # Update list of scheduled passes for API
            self._update_scheduled_passes_list()
                
            self.gs_logger.info(f"Scheduled pass at {pass_to_schedule.rise}")
            return True
            
    def _update_scheduled_passes_list(self):
        """Update the list of scheduled passes in tracking data"""
        # Get a copy of all passes without emptying the queue
        with self.lock:
            temp_queue = PriorityQueue()
            passes_list = []
            
            # Empty the queue into our list and temp queue
            while not self.scheduled_passes.empty():
                pass_obj = self.scheduled_passes.get()
                passes_list.append(pass_obj)
                temp_queue.put(pass_obj)
                
            # Restore the queue
            while not temp_queue.empty():
                self.scheduled_passes.put(temp_queue.get())
                
            # Update tracking data with serializable pass info
            self.tracking_data["scheduled_passes"] = [p.to_dict() for p in passes_list]

            # Update persistence file with current passes
            with open(os.path.join(PERSISTENCE_FOLDER, "schedueled_passes.json"), 'w') as f:
                for p in passes_list:
                    json.dump(p.to_dict(), f)
                    f.write('\n')

    
    def _start_scheduler(self):
        """Start the scheduler thread"""
        with self.lock:
            if self.is_scheduling:
                return
                
            self.scheduler_stop_event.clear()
            self.scheduler_thread = threading.Thread(target=self._scheduler_thread)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            self.is_scheduling = True
            self.gs_logger.info("Satellite pass scheduler started")
    
    def _scheduler_thread(self):
        """Thread that manages scheduled passes"""
        while not self.scheduler_stop_event.is_set():
            with self.lock:
                # If no passes scheduled, just check again later
                if self.scheduled_passes.empty():
                    self.lock.release()
                    try:
                        # Sleep for a minute then check again
                        self.scheduler_stop_event.wait(60)
                        if self.scheduler_stop_event.is_set():
                            break
                    finally:
                        # Reacquire lock
                        self.lock.acquire()
                    continue
                    
                # Peek at next pass
                next_pass = self.scheduled_passes.queue[0]
                now = datetime.now(timezone.utc)
                
                # If too far in the future, sleep and check again
                time_till_pass = (next_pass.rise - now).total_seconds() - 300  # 5 min before pass
                
                if time_till_pass > 60:  # If more than a minute away
                    # Release lock during sleep
                    self.lock.release()
                    try:
                        # Sleep for a minute then check again
                        self.scheduler_stop_event.wait(60)
                        if self.scheduler_stop_event.is_set():
                            break
                    finally:
                        # Reacquire lock
                        self.lock.acquire()
                    continue
                    
                # If it's time to prepare for the pass
                if time_till_pass <= 60:
                    # Remove from queue
                    self.scheduled_passes.get()
                    
                    # Start tracking if not already tracking
                    if not self.is_tracking:
                        self._start_tracking(next_pass)
                        
                    # Update scheduled passes list
                    self._update_scheduled_passes_list()
            
            # Sleep briefly before checking again
            self.scheduler_stop_event.wait(1)
    
    def _start_tracking(self, sat_pass: Pass):
        """
        Private method to start tracking a pass
        Only called by the scheduler
        """
        with self.lock:
            if self.is_tracking:
                return False

            self.track_stop_event.clear()

            # Update tracking data
            self.tracking_data["status"] = "waiting"
            self.tracking_data["current_pass"] = sat_pass

            # Start tracking thread
            self.tracking_thread = threading.Thread(
                target=self._track_satellite_thread,
                args=(sat_pass,)
            )
            self.tracking_thread.daemon = True
            self.tracking_thread.start()

            self.is_tracking = True
            self.gs_logger.info(f"Started tracking {self.satellite_name}, pass at {sat_pass.rise}")
            return True
            
    def _track_satellite_thread(self, sat_pass):
        """Thread that handles tracking during a pass"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._async_track_satellite(sat_pass))
        finally:
            loop.close()
            self._cleanup_tracking()
    
    async def _async_track_satellite(self, sat_pass):
        """Async method to track satellite during a pass"""
        # Sleep till the rise time
        now = datetime.now(timezone.utc)
        time_till_rise = (sat_pass.rise - now).total_seconds()
        
        if time_till_rise > 0:
            self.gs_logger.info(f"Waiting until rise time for {self.satellite_name}: {sat_pass.rise}")
            self.tracking_data["status"] = "waiting"
            
            try:
                # Sleep until rise time or until stopped
                await asyncio.wait_for(
                    asyncio.get_event_loop().create_future(), 
                    timeout=time_till_rise
                )
            except asyncio.TimeoutError:
                # This is expected when the timeout is reached
                pass
                
            # Check if we were stopped during wait
            if self.track_stop_event.is_set():
                self.gs_logger.info("Tracking was stopped during wait period")
                return
            
        # Update status
        self.tracking_data["status"] = "tracking"
        
        # Track the satellite during the pass
        while not self.track_stop_event.is_set():
            now = datetime.now(timezone.utc)
            
            # Check if the pass is over
            if now > sat_pass.set:
                self.gs_logger.info(f"Pass completed for {self.satellite_name}")
                break
            
            # Calculate position
            t = self.satellite.ts.now()
            difference = self.satellite.satellite - self.satellite.location
            topocentric = difference.at(t)
            alt, az, distance = topocentric.altaz()
            
            # Send azimuth, elevation to rotor controller
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
                
            # Sleep for a short time before updating
            await asyncio.sleep(1)

    def _cleanup_tracking(self):
        """Clean up after tracking has finished"""
        with self.lock:
            # Update status
            self.tracking_data["status"] = "idle"
            self.tracking_data["current_pass"] = None
            self.is_tracking = False
            
            self.gs_logger.info(f"Finished tracking satellite {self.satellite_name}")
    
    def cancel_pass(self, rise_time_iso: str) -> bool:
        """
        Cancel a scheduled pass by its rise time
        Args:
            rise_time_iso: ISO formatted rise time string (from the pass.to_dict() output)
        """
        with self.lock:
            rise_time = datetime.fromisoformat(rise_time_iso).replace(tzinfo=timezone.utc)
            
            # Search for the pass with the matching rise time
            temp_queue = PriorityQueue()
            found = False
            
            while not self.scheduled_passes.empty():
                pass_obj = self.scheduled_passes.get()
                
                # If this is the pass we're looking for, don't put it back
                if abs((pass_obj.rise - rise_time).total_seconds()) < 3600:  # Within 1 hour
                    found = True
                    self.gs_logger.info(f"Cancelled pass at {pass_obj.rise}")
                else:
                    temp_queue.put(pass_obj)
                
            # Restore the queue (minus the cancelled pass)
            while not temp_queue.empty():
                self.scheduled_passes.put(temp_queue.get())
                
            # Update tracking data
            self._update_scheduled_passes_list()
            
            return found
    
    def stop_scheduler(self):
        """Stop the scheduler and clear all scheduled passes"""
        with self.lock:
            self.scheduler_stop_event.set()
            
            # Wait for thread to finish (with timeout)
            if self.scheduler_thread and self.scheduler_thread.is_alive():
                self.scheduler_thread.join(timeout=2.0)
                
            # Clear all scheduled passes
            while not self.scheduled_passes.empty():
                self.scheduled_passes.get()
                
            self._update_scheduled_passes_list()
            self.is_scheduling = False
            
            # Also stop any ongoing tracking
            if self.is_tracking:
                self.track_stop_event.set()
                if self.tracking_thread and self.tracking_thread.is_alive():
                    self.tracking_thread.join(timeout=2.0)
                self._cleanup_tracking()
                
            self.gs_logger.info("Stopped scheduler and cleared all scheduled passes")
            return True
    
    def get_tracking_data(self):
        """Get the latest tracking data including scheduled passes"""
        with self.lock:
            return {
                "satellite": self.satellite_name,
                "azimuth": self.tracking_data["azimuth"],
                "elevation": self.tracking_data["elevation"],
                "distance": self.tracking_data["distance"],
                "status": self.tracking_data["status"],
                "last_updated": self.tracking_data["last_updated"],
                "current_pass": self.tracking_data["current_pass"].to_dict() if self.tracking_data["current_pass"] else None,
                "scheduled_passes": self.tracking_data["scheduled_passes"]
            }
