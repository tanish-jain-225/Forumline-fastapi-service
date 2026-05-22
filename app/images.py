import os
from dotenv import load_dotenv

from imagekitio import ImageKit

load_dotenv()

imagekit_private_key = os.getenv("IMAGEKIT_PRIVATE_KEY")

if imagekit_private_key:
    imageKit = ImageKit(private_key=imagekit_private_key)
else:
    imageKit = None

