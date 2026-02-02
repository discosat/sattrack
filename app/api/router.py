import websockets
import json
import time
import asyncio
from pydantic import BaseModel
from typing import List, Any
import subprocess
from datetime import datetime
from pathlib import Path



header = {"Authorization" : "Bearer test-user"}

token = "Authorization: Bearer test-user"


hello_msg = {"type" : "hello", "name" : "test-gs", "token" : token}

hello_terminal_msg = {"type" : "connect_ro", "name" : "test-terminal", "token" : token}


config_dir = Path(__file__).parent.resolve() / ".." / "config" 


class APIMethod(BaseModel):
    args: List[Any]
    description: str

class TimeStamp(BaseModel):
    pass

class Option:

    def __init__(self, basetype):
        if type(basetype) == TimeStamp:
            self.__name__ = "Optional timestamp" 
        else:
            self.__name__ = "Optional " + basetype.__name__
        self.basetype = basetype


def type_marshaller(typ):
    if typ == int:
        return "int"
    elif typ == float:
        return "float"
    elif typ == str:
        return "str"

def api_method_to_dict(name, obj):
    args = []
    for i in obj.args:
        args.append(type_marshaller(i))

    return {"name" : name, "args" : args, "description" : obj.description}


def typecheck(received, expected):

    if type(expected) == list: 

        if len(received) > len(expected):
            return "too many arguments"

        elif len(received) < len(expected):
            return "too few arguments"

        for r,e in zip(received, expected):            
            res = typecheck(r, e) 
            if res != "ok":
                return res   
        return "ok"


    if type(received) == expected:
        return "ok"
    if type(received) == int and expected == float:
        return "ok"
    
    if type(received) == str and expected == TimeStamp:
        try:
            datetime.fromisoformat(received)
            return "ok"
        except:
            return "could not parse datetime format"


    if received is None and isinstance(expected, Option):
        return "ok"

    if received is not None and isinstance(expected, Option):
        return typecheck(received, expected.basetype)

    return f"mismatched types expected {expected.__name__} but got {type(received).__name__}"



class Router:
    def __init__(self, logger, platform_ip, platform_port, tracker, tle_script):
        self.logger = logger
        self.tracker = tracker
        self.rotor = tracker.get_rotor()
        self.tle_script = tle_script

        supported_methods = {

                "get_apis" : APIMethod(args=[], description="""
                returns api usage info
                """),

                "update_tle_data" : APIMethod(args=[str], description="""
                makes the sattracker download the tle data from the internet 
                args:
                name: str -- the name of the satellite to track
                """),

                "reload_tle_data" : APIMethod(args=[], description="""
                makes the sattracker reload the tle data from file 
                """),

                "get_gs_loc" : APIMethod(args=[], description="""
                get the location of the groundstation
                returns: {lat : <value>, lon : <value>}
                lat: float -- latitude in decimal degrees format
                lon: float -- longitude in decimal degrees format
                """),

                "set_gs_loc" : APIMethod(args=[float, float], description="""
                set the groundstation location
                args:
                lat: float -- latitude in decimal degrees format
                lon: float -- longtitude in decimal degrees format
                returns: nothing
                notes:
                This change is persistent
                """),






                "get_next_pass" : APIMethod(args=[Option(float)], description="""
                get the next pass
                args:
                min_elevation: Opional float -- the minimium elevation a pass must reach to be considered valid
                returns: {"rise" : <value>, "culminate" : <value>, "set" : <value>}
                rise: timestamp -- the utc time in iso format where the pass is considered started
                culminate: timestamp -- the utc time in iso format when the satellite is highest in the sky
                set: timestamp -- the utc time in iso format when the pass is considered ended
                notes:
                if the min_elevation parameter is null it defaults to 5 degrees
                """), 

                "get_sat_passes" : APIMethod(args=[Option(TimeStamp), Option(TimeStamp), Option(float)], description="""
                get all the passes within a specific timeframe
                args:
                start: Optional timestamp -- the utc time in iso format where the interval to search for passes starts
                stop: Optional timestamp  -- the utc time in iso format to stop looking for passes 
                min_elevation: Optional float -- the minimium elevation a pass must reach to be considered valid
                returns {passes : [[pass_1_start, pass_1_end], [pass_2_start, pass_2_end] ... <pass_n>]}
                pass_start: timestamp -- the utc time in iso format where the pass is considered started
                pass_end: timestamp -- the utc time in iso format where the pass is considered ended
                notes:
                Some arguments are optional, if you wish to not specify them provide the null/None object/type instead.
                This is important since the argument ordering is important
                if the start argument is not given the timeframe is from here on out
                if the stop argument is not given we stop searching for passes exactly a day from the start time
                if the min_elevation argument is not given it defaults to 5 degrees
                """), 



                "get_tracking_data" : APIMethod(args=[], description="""
                get the tracking status of the satellite
                returns {name : <value>, tracking : <value>, status : <value>}
                name: str -- the name of the tracked satellite
                tracking: bool -- true if the satellite is currently tracked
                status: no clue HELP
                """), 



                "schedule_pass" : APIMethod(args=[TimeStamp], description="""
                schedule a pass. the rotor will point but this method will not run any script
                good for testing or running csh scripts manually
                args:
                time: str -- the utc time in iso format where the pass is considered started
                """), 

                "track" : APIMethod(args=[], description="""
                track the satellite forever. the rotor will point but this method will not run any script
                good for testing or running csh scripts manually
                args:
                """),

                "cancel_pass" : APIMethod(args=[TimeStamp], description="""
                cancel the specific pass  
                args:
                pass_start: timestamp -- the utc time in iso format where the pass is considered started
                """), 

                "cancel_all_passes" : APIMethod(args=[], description="""
                cancel all passes
                """),

                "get_rotor_pos" : APIMethod(args = [], description = """
                returns: { azimuth : az, elevation: el}
                az: int -- the current azimuth bearing
                el: int -- the current elevation bearing
                """),

                "set_rotor_pos" : APIMethod(args = [int, int], description = """
                args:
                azimuth: int -- the current azimuth bearing
                elevation: int -- the current elevation bearing
                """)
        }

        methods_to_support = {

                "help" : APIMethod(args=[], description="""
                returns general usage info
                """),


                "get_sat_status" : APIMethod(args=[], description="""
                get the tracking status of the satellite
                returns {name : <value>, tracking : <value>, status : <value>}
                name: str -- the name of the tracked satellite
                tracking: bool -- true if the satellite is currently tracked
                status: no clue HELP
                """), 

                "get_sat_pos" : APIMethod(args=[], description="""
                get current satellite position
                returns NO CLUE
                """), 


                ## get tracking data ??


                "schedule_transmission" : APIMethod(args=[TimeStamp], description="""
                schedule a transmission. This means the rotor will point AND a flight plan will be uploaded
                args:
                time: str -- the utc time in iso format where the pass is considered started
                frames: [csh_script: str]
                notes:
                use the framed control platform endpoint to use this method
                """), 

        }

        self.methods = supported_methods | methods_to_support 

        self.id = None

        descriptions = []

        for name,method in self.methods.items():
            descriptions.append(api_method_to_dict(name,method))
        
        self.method_descriptions = descriptions

        self.platform_ip = platform_ip
        self.platform_port = platform_port


    async def connect(self):
        self.socket = await websockets.connect(f"ws://{self.platform_ip}:{self.platform_port}/api/gs/ws", additional_headers=header)
        await self.write_ws(hello_msg)
        msg = await self.socket.recv()
        msg = json.loads(msg)
        
        status = msg.get("message")
        if status != "OK":
            self.logger.critical("could not connect to platform")
            exit(1)

        self.id = msg.get("id")
        self.logger.info(f"gs_id: {self.id}")


    async def read_ws(self):
        msg = await self.socket.recv()
        self.logger.debug(f"reading from websocket: {msg}")
        return msg


    async def framed_read_ws(self, frame_num):
        if frame_num < 1:
            return

        frames = []
        for i in range(0, frame_num):
            frames.append(await self.read_ws())
        self.logger.info(f"reading {frame_num} frames")


    async def write_ws(self, msg):
        await self.socket.send(json.dumps(msg))


    async def parse_msg(self, msg):

        reply = {"type" : "terminal/piss"}

        request_id = msg.get("request_id")
        if not request_id is None:
            reply["in_response_to"] = request_id


        proxy_header = msg.get("proxy_header")
        if not proxy_header is None:
            origin = proxy_header.get("origin")
            # currently do nothing with this header


        frame_num = msg.get("frames")
        if not frame_num is None:
            frame_num = int(frame_num)
            frames = await self.framed_read_ws(frame_num)
        

        data = msg.get("data")
        if data is None:
            reply["error"] = "no data field"
            return reply      

        msg_type = data.get("type")
        if msg_type is None:
            reply["error"] = "no msg_type included"
            return reply

        

        ## from here all handling assumes api calls
        if msg_type != "api_call":
            reply["error"] = "type only supports 'api_call'"
            return reply

        api = data.get("api")
        if api is None:
            reply["error"] = "no method specified"
            return reply
        
        
        api_description = self.methods.get(api, None)
        if api_description is None:
            reply["error"] = "no such api"
            return reply
        args = data.get("args", [])
        type_res = typecheck(args, api_description.args)

        
        if type_res != "ok":
            reply["error"] = type_res
            return reply


        ## only correctly typechecked methods
 
        elif api == "get_apis":
            reply["data"] = self.method_descriptions

 
        elif api == "get_gs_loc":
            location = self.tracker.satellite.location
            lat = location.latitude.degrees
            lon = location.longitude.degrees
            reply["data"] = {"lat" : lat, "lon" : lon}


        elif api == "set_gs_loc":
            lat, lon = args
            print("opening file")
            with open(config_dir / "location.txt", "w") as file:
                file.write(f"{lat}\n{lon}")
            self.tracker.satellite._load_gs_location()
            reply["data"] = "ok"


        elif api == "get_sat_status":
            result = self.tracker.get_tracking_data()
            reply["data"] = result

        elif api == "get_tracking_data":
            reply["data"] = self.tracker.get_tracking_data()


        

        elif api == "reload_tle_data":
            result = self.tracker.reload_satellite()
            if result:
                reply["data"] = "ok"
            else:
                reply["error"] = "cannot reload tle data while sattelite is being tracked"


        elif api == "update_tle_data":
            name = args[0]
            result = subprocess.run([self.tle_script, name]).returncode
            if result == 0:
                reply["data"] = "ok"
            elif result == 2:
                reply["error"] = "cannot reach celestrack"
            elif result == 1:
                reply["error"] = "error downloading tle data"

        
        elif api == "get_next_pass":
            result = self.tracker.satellite.get_next_pass(args[0]) 
            if result is not None:
                reply["data"] = result.to_dict()
            else:
                reply["error"] = "no suitable passes can be found"

        elif api == "get_sat_passes":
            start, end, min_float = args
            if start is not None:
                start = datetime.fromisoformat(start)
            if end is not None:
                end = datetime.fromisoformat(end)
            passes = self.tracker.satellite.get_passes(start, end, min_float)
            result = []
            for p in passes:
                result.append(p.to_dict())
            
            reply["data"] = result

        elif api == "schedule_pass":
            time = datetime.fromisoformat(args[0])
            result = self.tracker.schedule_pass(time)
            if result:
                reply["data"] = "ok"
            else:
                reply["error"] = "could not schedule pass"

        
        elif api == "track":
            self.tracker.submit_all_passes()
            reply["data"] = "ok"

        elif api == "cancel_pass":
            result = self.tracker.cancel_pass(args[0])
            if result:
                reply["data"] = "ok"
            else:
                reply["error"] = "could not find specified pass"


        elif api == "cancel_all_passes":
            self.tracker.stop_scheduler()
            self.tracker._start_scheduler()
            reply["data"] = "ok"

            



        elif api == "get_rotor_pos":
            az, el = await self.rotor.read()
            reply["data"] = {"azimuth" : az, "elevation" : el}

        elif api == "set_rotor_pos":
            az, el = args 
            await self.rotor.write(az,el)
            reply["data"] = "ok"

        else:
            reply["error"] = "not implemented"
        

        self.logger.debug(f"replying with: {reply}")
        return reply



    # consider using in queues and out queues
    # this does not make sense since the the satop platform sends frame data in serial order
    # this means communication (using this websocket at least) can not be parallel
    async def work(self):
        try: 
            while True:
                msg = await self.read_ws()
                msg = json.loads(msg) 
                reply = await self.parse_msg(msg)
                await self.write_ws(json.dumps(reply)) 
        except Exception as e:
            print(e) 
            print("connection closed :)")
            return None

