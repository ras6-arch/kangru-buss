import csv, io, json, os, zipfile, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GTFS_URL='https://eu-gtfs.remix.com/harjumaa.zip'
LINES={'116','116A','116B','116C'}
HOME_STOPS={'Kangru','Põdra tee'}
CITY_STOPS={'Viru','Kosmos','Kalev','Hallivanamehe','Viljandi maantee'}
TZ=ZoneInfo('Europe/Tallinn')
STOP_ALIASES={'Viljandi mnt':'Viljandi maantee','Viljandi maantee':'Viljandi maantee'}

def read_csv(z,name):
    with z.open(name) as f:return list(csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig')))
def parse_minutes(s):
    h,m,_=map(int,s.split(':'));return h*60+m
def normalize_stop(name):return STOP_ALIASES.get(name,name)
def service_dates(calendar_rows,exception_rows):
    today=datetime.now(TZ).date();first=today-timedelta(days=1);end=today+timedelta(days=120);out=defaultdict(set);weekdays=['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    for r in calendar_rows:
        start=max(first,datetime.strptime(r['start_date'],'%Y%m%d').date());stop=min(end,datetime.strptime(r['end_date'],'%Y%m%d').date());d=start
        while d<=stop:
            if r[weekdays[d.weekday()]]=='1':out[r['service_id']].add(d)
            d+=timedelta(days=1)
    for r in exception_rows:
        d=datetime.strptime(r['date'],'%Y%m%d').date()
        if not(first<=d<=end):continue
        if r['exception_type']=='1':out[r['service_id']].add(d)
        elif r['exception_type']=='2':out[r['service_id']].discard(d)
    return out
def to_iso(d,mins):
    d=d+timedelta(days=mins//1440);mins%=1440;return datetime(d.year,d.month,d.day,mins//60,mins%60,tzinfo=TZ).isoformat()
def hhmm(mins):
    mins%=1440;return f'{mins//60:02d}:{mins%60:02d}'

def load_previous_entries():
    if not os.path.exists('timetable.json'):return []
    try:
        with open('timetable.json',encoding='utf-8') as f:return json.load(f).get('entries',[])
    except Exception:return []

previous_entries=load_previous_entries()
raw=urllib.request.urlopen(GTFS_URL,timeout=60).read();z=zipfile.ZipFile(io.BytesIO(raw));routes=read_csv(z,'routes.txt');trips=read_csv(z,'trips.txt');stops=read_csv(z,'stops.txt');stop_times=read_csv(z,'stop_times.txt');calendar=read_csv(z,'calendar.txt') if 'calendar.txt' in z.namelist() else [];calendar_dates=read_csv(z,'calendar_dates.txt') if 'calendar_dates.txt' in z.namelist() else []
route_line={r['route_id']:r['route_short_name'] for r in routes if r.get('route_short_name') in LINES};trip_info={t['trip_id']:(route_line[t['route_id']],t['service_id']) for t in trips if t.get('route_id') in route_line};stop_name={s['stop_id']:normalize_stop(s['stop_name']) for s in stops};needed=HOME_STOPS|CITY_STOPS;by_trip=defaultdict(list)
for st in stop_times:
    tid=st['trip_id']
    if tid not in trip_info:continue
    name=stop_name.get(st['stop_id'])
    if name not in needed:continue
    dep=st.get('departure_time') or st.get('arrival_time');arr=st.get('arrival_time') or st.get('departure_time')
    if not dep or not arr:continue
    by_trip[tid].append((int(st['stop_sequence']),name,parse_minutes(dep),parse_minutes(arr)))
services=service_dates(calendar,calendar_dates);entries=[];seen=set()
for tid,pts in by_trip.items():
    line,service_id=trip_info[tid];pts=sorted(pts);homes=[p for p in pts if p[1] in HOME_STOPS];cities=[p for p in pts if p[1] in CITY_STOPS]
    for service_date in sorted(services.get(service_id,())):
        for h in homes:
            for c in cities:
                if h[0]<c[0]:direction,origin,destination='city',h,c
                elif c[0]<h[0]:direction,origin,destination='home',c,h
                else:continue
                dep_m,arr_m=origin[2],destination[3];actual_date=service_date+timedelta(days=dep_m//1440);key=(actual_date.isoformat(),line,direction,origin[1],destination[1],dep_m,arr_m)
                if key in seen:continue
                seen.add(key);entries.append({'date':actual_date.isoformat(),'line':line,'direction':direction,'origin':origin[1],'destination':destination[1],'departure':hhmm(dep_m),'arrival':hhmm(arr_m),'dep_iso':to_iso(service_date,dep_m),'arr_iso':to_iso(service_date,arr_m)})

now=datetime.now(TZ);today=now.date().isoformat();day0=datetime(now.year,now.month,now.day,tzinfo=TZ);carry_limit=day0+timedelta(days=1,hours=4)
if not any(e['date']==today for e in entries) and previous_entries:
    carry=[]
    for e in previous_entries:
        try: dep=datetime.fromisoformat(e['dep_iso'])
        except Exception: continue
        if day0<=dep<carry_limit:carry.append(e)
    existing={(e['dep_iso'],e['line'],e['direction'],e['origin'],e['destination']) for e in entries}
    added=0
    for e in carry:
        key=(e['dep_iso'],e['line'],e['direction'],e['origin'],e['destination'])
        if key not in existing:
            entries.append(e);existing.add(key);added+=1
    print(f'GTFS rollover: preserved {added} existing rows through {carry_limit.isoformat()}')

entries.sort(key=lambda x:(x['dep_iso'],x['line'],x['destination']))
if not entries:raise RuntimeError('Official transport data produced zero timetable rows for lines 116/116A/116B/116C')
with open('timetable.json','w',encoding='utf-8') as f:json.dump({'generated_at':datetime.now(TZ).isoformat(),'source':GTFS_URL,'entries':entries},f,ensure_ascii=False,separators=(',',':'))
print(f'Wrote {len(entries)} timetable rows');limit=now+timedelta(hours=4);found=[e for e in entries if e['direction']=='city' and e['destination']=='Viru' and now<=datetime.fromisoformat(e['dep_iso'])<=limit];print('CHECK Viru next4h:',[(e['line'],e['origin'],e['departure'],e['arrival']) for e in found])
