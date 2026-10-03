"""Frozen conservative lexical baseline; independent of benchmark predictions.

This implementation matches explicit metric phrases and priority markers.
It does not use workload names or telemetry.
"""
import re
METRICS={
 'tps':(r'\bTPS\b|transactions per second','throughput','max'),
 'ops_s':(r'operations/s|operations per second','throughput','max'),
 'p95_ms':(r'\bP95\b|\bp95_ms\b|95th percentile','tail_latency','min'),
 'p99_ms':(r'\bP99\b|\bp99_ms\b|99th percentile','tail_latency','min'),
 'completion_s':(r'completion time|completion_s','completion_time','min'),
 'throughput_cv':(r'throughput CV|coefficient of variation of throughput','stability','min'),
}
def infer(text):
 constraints={}
 if re.search(r'synchronous durability',text,re.I): constraints['durability']='sync'
 if re.search(r'write barriers enabled',text,re.I): constraints['barriers']='on'
 for pattern,key in [
  (r'P95\s*<=\s*([\d.]+)\s*ms','p95_max_ms'),
  (r'P99\s*<=\s*([\d.]+)\s*ms','p99_max_ms'),
  (r'(?:throughput CV must remain <=)\s*([\d.]+)','cv_max'),
  (r'commit interval (?:at most|remains at most)\s*([\d.]+)\s*seconds','commit_max_s'),
  (r'at least\s*([\d.]+)\s*(?:operations/s|TPS)','throughput_min'),
  (r'Operations/s must be at least\s*([\d.]+)','throughput_min'),
 ]:
  match=re.search(pattern,text,re.I)
  if match: constraints[key]=float(match[1])
 # Explicit primary/current markers are handled before generic keyword matching.
 scope=text
 for marker in [r'current instruction replaces it:',r'current primary objective is',r'primary (?:goal|objective) is',r'only (?:objective|target) is',r'rank candidates solely by']:
  hit=re.search(marker,text,re.I)
  if hit: scope=text[hit.end():].split('.')[0]; break
 scope=re.split(r' subject to | while |;|, maintaining ',scope,flags=re.I)[0]
 # An old objective, two simultaneous metrics, or unspecified preference abstains.
 found=[m for m,(pat,_,_) in METRICS.items() if re.search(pat,scope,re.I)]
 goal=bool(re.search(r'maximiz|minimiz|minimum|maximum|lowest|highest|smallest|reduce',scope,re.I))
 conflict=bool(re.search(r'equally|no priority|no trade-off|not agreed|maximize and minimize|neither',scope,re.I))
 resolved=goal and len(found)==1 and not conflict
 m=found[0] if resolved else None
 return {'status':'resolved' if resolved else 'abstain','category':METRICS[m][1] if m else None,
  'metric':m,'direction':METRICS[m][2] if m else None,'constraints':constraints,
  'evidence':scope if resolved else text,'reason':'Frozen conservative lexical extraction.'}
