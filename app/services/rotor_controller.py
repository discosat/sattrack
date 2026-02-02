import asyncio
import threading


async def connect():
    reader, writer = await asyncio.open_connection("192.168.1.9", 4533) 
    return reader, writer

def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


class RotorController:
    reader = None
    writer = None

    @classmethod
    async def initialize(cls):
        if cls.reader is None:
            
            # start a new seperate thread with event loop to handle the asyncio connection
            loop = asyncio.new_event_loop()

            threading.Thread(target=start_loop, args=(loop,), daemon=True).start()
            reader, writer = asyncio.run_coroutine_threadsafe(connect(), loop).result()

            cls.reader = reader
            cls.writer = writer 
            cls.loop = loop

            # we can only handle one read or write at a time
            cls.mutex = threading.Lock() 
        return cls


    # TODO
    # since we can only do one read or write at a time, and writes are more important
    # it could make sense to cache this value.
    # but if reads are infrequent this is fine
    @classmethod
    async def _read(cls):
        with cls.mutex:
            cls.writer.write("p".encode())
            await cls.writer.drain()
            response = await cls.reader.read(64)
    
        response = response.decode()
        response = response.splitlines()
        az = response[0]
        el = response[1] 
        return az, el
    
    @classmethod
    async def read(cls):
        future = asyncio.run_coroutine_threadsafe(cls._read(), cls.loop)
        return future.result()


    @classmethod
    async def _write(cls, az, el):
        with cls.mutex:
            cls.writer.write(f"P {az} {el}".encode())
            await cls.writer.drain()
            response = await cls.reader.read(64)
        return
    
    @classmethod
    async def write(cls, az, el):
        future = asyncio.run_coroutine_threadsafe(cls._write(az, el), cls.loop)
        future.result()
        return


class DebugRotorController:

    @classmethod
    async def initialize(cls):
        return cls


    @classmethod
    async def read(cls):
        print("reading from rotor controller")
        return 0, 0

    @classmethod
    async def write(cls, az, el):
        print(f"writing {az},{el} to rotor controller")
