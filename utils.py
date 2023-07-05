from concurrent.futures import ProcessPoolExecutor
from threading import Lock
import time,sys,json

class PPWrapper:
    def __init__(self, func):
        self.func = func
    def run(self, *args, **kwargs):
        try:
            return self.func(*args, **kwargs)
        except Exception as e:
            print(f"Error when run process e='{e}'", flush=True)
            raise e
        finally:
            sys.stdout.flush()
        
class PP:
    def __init__(self, num=1, callback=None):
        self.thread_num = num
        self.pool =  ProcessPoolExecutor(max_workers=self.thread_num)
        self.run_num = 0
        self.max_rum_num = 2* self.thread_num
        self.lock = Lock()
        self.callback = callback
        
    def submit(self, func, *args, **kwargs):
        while True:
            if self.run_num >= self.max_rum_num:
                time.sleep(0.004)
            else:
                break
        ppw = PPWrapper(func)
        future = self.pool.submit(ppw.run,  *args, **kwargs)
        self.lock.acquire()
        self.run_num += 1
        self.lock.release()
        future.add_done_callback(self._when_done_one)

    def close(self):
        import time
        time.sleep(1)
        self.pool.shutdown(wait=True)
        # self.pool.shutdown(wait=True, cancel_futures=True)

    def _when_done_one(self, future):
        self.lock.acquire()
        self.run_num -= 1
        self.lock.release()
        if self.callback:
            res = future.result()
            # print(res)
            self.callback(res)    