"""Local launcher; never opens a browser automatically or runs a production worker."""
from pathlib import Path
import argparse,os,sys
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--source',action='store_true',help='Run this source checkout without verifying the frozen review candidate');a=p.parse_args()
    if not 1024<=a.port<=65535:raise ValueError('Port range1024..65535')
    os.environ['SCATTER_REVIEW_PORT']=str(a.port)
    sys.dont_write_bytecode=True
    candidate=Path(__file__).resolve().parent/'active_candidate.json'
    if candidate.exists() and not a.source:
        from verify_candidate import verify
        print('Frozen source:',verify())
    else:
        print('Local source checkout; frozen review candidate is not verified')
    import uvicorn
    uvicorn.run('server:app',host='127.0.0.1',port=a.port,app_dir=str(Path(__file__).resolve().parent),log_level='info',access_log=False)
if __name__=='__main__':main()
