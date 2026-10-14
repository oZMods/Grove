"""Cancellable, bounded condition polling on the caller's event loop."""
import math
import time

class ConditionTask:
    def __init__(self,scheduler,condition,timeout_seconds,interval_ms=100,on_complete=None,clock=time.monotonic):
        if not math.isfinite(timeout_seconds) or timeout_seconds<=0 or not isinstance(interval_ms,int) or interval_ms<=0:
            raise ValueError('Polling requires positive bounded timeout and interval.')
        self.scheduler,self.condition,self.interval=scheduler,condition,interval_ms
        self.callback,self.clock=on_complete,clock
        self.deadline=clock()+timeout_seconds
        self.status='pending'
        self.result=self.error=self.scheduled=None
    def start(self):
        if self.status!='pending':raise RuntimeError('Condition task already started.')
        self.status='running'
        self.poll()
        return self
    def finish(self,status,result=None,error=None):
        if self.status!='running':return
        self.status,self.result,self.error=status,result,error
        if self.callback:self.callback(self)
    def poll(self):
        if self.status!='running':return
        try:
            result=self.condition()
            if result:self.finish('completed',result);return
            if self.clock()>=self.deadline:self.finish('timed_out');return
            self.scheduled=self.scheduler.after(self.interval,self.poll)
        except Exception as error:self.finish('failed',error=error)
    def cancel(self):
        if self.status not in ('pending','running'):return
        self.status='cancelled'
        if self.scheduled is not None and hasattr(self.scheduler,'after_cancel'):
            self.scheduler.after_cancel(self.scheduled)
