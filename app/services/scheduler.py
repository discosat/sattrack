import threading
from datetime import datetime, timezone, timedelta
from queue import PriorityQueue
from typing import List, Optional

class PassScheduler:
    def __init__(self, satellite_tracker):
        self.satellite_tracker = satellite_tracker
        self.logger = satellite_tracker.gs_logger
        self.scheduled_passes = PriorityQueue()  # Priority queue ordered by pass rise time
        self.scheduler_thread = None
        self.is_running = False
        self.current_pass = None
        self.lock = threading.Lock()  # For thread safety
    
    def start_scheduler(self):
        """Start the pass scheduler thread"""
        if self.is_running:
            return False
        
        self.is_running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        self.logger.info("Pass scheduler started")
        return True
    
    def stop_scheduler(self):
        """Stop the pass scheduler"""
        if not self.is_running:
            return False
        
        self.is_running = False
        if self.satellite_tracker.is_tracking:
            self.satellite_tracker.stop_tracking()
        
        self.logger.info("Pass scheduler stopped")
        return True
    
    def schedule_pass(self, pass_obj):
        """Schedule a satellite pass"""
        with self.lock:
            # Check if pass is in the future
            now = datetime.now(timezone.utc)
            if pass_obj.rise <= now:
                self.logger.error("Cannot schedule a pass that has already started")
                return False
            
            # Check if pass is within one week
            one_week_later = now + timedelta(days=7)
            if pass_obj.rise > one_week_later:
                self.logger.error("Cannot schedule passes more than one week in advance")
                return False
            
            # Check for overlap with existing scheduled passes
            if self._is_overlapping(pass_obj):
                self.logger.error("This pass overlaps with an already scheduled pass")
                return False
            
            # Add to priority queue (priority is the rise time)
            self.scheduled_passes.put((pass_obj.rise, pass_obj))
            self.logger.info(f"Scheduled pass for {self.satellite_tracker.satellite_name} at {pass_obj.rise}")
            return True
    
    def _is_overlapping(self, new_pass):
        """Check if the new pass overlaps with any scheduled passes"""
        # Copy the queue to check all items without removing them
        temp_queue = PriorityQueue()
        has_overlap = False
        
        while not self.scheduled_passes.empty():
            priority, pass_obj = self.scheduled_passes.get()
            
            # Check for overlap
            if (new_pass.rise < pass_obj.set and new_pass.set > pass_obj.rise):
                has_overlap = True
            
            # Put the pass back in the temporary queue
            temp_queue.put((priority, pass_obj))
        
        # Restore the original queue
        while not temp_queue.empty():
            self.scheduled_passes.put(temp_queue.get())
        
        return has_overlap
    
    def get_scheduled_passes(self) -> List[dict]:
        """Get a list of all scheduled passes"""
        passes = []
        temp_queue = PriorityQueue()
        
        # Extract all passes from the priority queue
        while not self.scheduled_passes.empty():
            priority, pass_obj = self.scheduled_passes.get()
            passes.append(pass_obj)
            temp_queue.put((priority, pass_obj))
        
        # Restore the queue
        while not temp_queue.empty():
            self.scheduled_passes.put(temp_queue.get())
        
        # Convert passes to dictionaries for serialization
        return [p.to_dict() for p in passes]
    
    def schedule_next_passes(self, count=5):
        """Schedule the next available passes that don't overlap"""
        with self.lock:
            now = datetime.now(timezone.utc)
            start_time = now
            scheduled_count = 0
            max_attempts = count * 3  # Allow some attempts for finding non-overlapping passes
            attempt = 0
            
            while scheduled_count < count and attempt < max_attempts:
                # Find the next pass starting from the last end time
                next_pass = self.satellite_tracker._get_next_pass(deg=10.0, start_date=start_time)
                if not next_pass:
                    break
                
                # Check if it's within one week
                one_week_later = now + timedelta(days=7)
                if next_pass.rise > one_week_later:
                    break
                
                # Check for overlap
                if not self._is_overlapping(next_pass):
                    self.scheduled_passes.put((next_pass.rise, next_pass))
                    scheduled_count += 1
                    self.logger.info(f"Auto-scheduled pass at {next_pass.rise}")
                
                # Move start time to after this pass ends
                start_time = next_pass.set + timedelta(minutes=1)
                attempt += 1
            
            return scheduled_count
    
    def _scheduler_loop(self):
        """Main scheduler loop that runs in a separate thread"""
        while self.is_running:
            now = datetime.now(timezone.utc)
            
            # Check if there's a pass to execute
            if not self.satellite_tracker.is_tracking and not self.scheduled_passes.empty():
                with self.lock:
                    # Get the next pass without removing it
                    next_pass_time, next_pass = self.scheduled_passes.queue[0]
                    
                    # Start tracking if it's time (5 minutes before rise time)
                    if now >= next_pass_time - timedelta(minutes=5):
                        # Remove from queue
                        self.scheduled_passes.get()
                        
                        # Start tracking for this pass
                        self.current_pass = next_pass
                        self.satellite_tracker.start_tracking(start_date=next_pass.rise)
                        self.logger.info(f"Starting tracking for scheduled pass at {next_pass.rise}")
            
            # If tracking is done but there was a current pass, clear it
            if not self.satellite_tracker.is_tracking and self.current_pass:
                if now > self.current_pass.set:
                    self.current_pass = None
            
            # Sleep for a short time
            threading.Event().wait(10)  # Check every 10 seconds