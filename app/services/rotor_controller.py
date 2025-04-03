import asyncio

class RotorController:
    reader = None
    writer = None

    @classmethod
    async def initialize(cls):
        return cls

    @classmethod
    async def read(cls):
        return 50, 50


    @classmethod
    async def write(cls, az, el):
        print(f"setting az:{az} el:{el}")