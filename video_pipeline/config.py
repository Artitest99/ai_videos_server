# from dotenv import load_dotenv
# import os

# load_dotenv()  # Automatically looks for a .env file
# FILE_NAME = os.getenv("FILE_NAME")
# print(FILE_NAME)

env_vars = {} # or dict {}
dict={}
with open(".env") as f:
    for line in f:
        if line.startswith('#') or not line.strip():
            continue
        # if 'export' not in line:
        #     continue
        # Remove leading `export `, if you have those
        # then, split name / value pair
        # key, value = line.replace('export ', '', 1).strip().split('=', 1)
        key, value = line.strip().split('=', 1)
        # os.environ[key] = value  # Load to local environ
        # env_vars[key] = value # Save to a dict, initialized env_vars = {}
        env_vars[key] = value
        
FILE_NAME = env_vars["FILE_NAME"] 
MUSIC = env_vars["MUSIC"] 
FPS = env_vars["FPS"] 
print(FILE_NAME)