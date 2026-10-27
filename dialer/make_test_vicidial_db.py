"""Builds a small Vicidial-like test database (vici_test) with the four standard tables and a few rows. Edit host, port and user below."""
import time
import pymysql
c = pymysql.connect(host="127.0.0.1", port=3307, user="root", password="", charset="utf8mb4", autocommit=True)
cur = c.cursor()
cur.execute("drop database if exists vici_test"); cur.execute("create database vici_test"); cur.execute("use vici_test")
cur.execute("""create table vicidial_closer_log (closecallid int auto_increment primary key, lead_id int, list_id bigint, campaign_id varchar(20), call_date datetime, start_epoch int, end_epoch int,
  length_in_sec int, status varchar(6), phone_code varchar(10), phone_number varchar(18), user varchar(20), comments varchar(255), processed enum('Y','N'), queue_seconds decimal(7,2), user_group varchar(20),
  xfercallid int, term_reason varchar(30), uniqueid varchar(20), agent_only varchar(20), queue_position smallint, called_count smallint)""")
cur.execute("""create table vicidial_log (uniqueid varchar(20), lead_id int, list_id bigint, campaign_id varchar(20), call_date datetime, start_epoch int, end_epoch int, length_in_sec int, status varchar(6),
  phone_code varchar(10), phone_number varchar(18), user varchar(20), comments varchar(255), processed enum('Y','N'), user_group varchar(20), term_reason varchar(30), alt_dial varchar(6), called_count int)""")
cur.execute("""create table recording_log (recording_id int auto_increment primary key, channel varchar(100), server_ip varchar(15), extension varchar(100), start_time datetime, start_epoch int, end_time datetime,
  end_epoch int, length_in_sec int, length_in_min double, filename varchar(100), location varchar(255), lead_id int, user varchar(20), vicidial_id varchar(20))""")
cur.execute("""create table vicidial_agent_log (agent_log_id int auto_increment primary key, user varchar(20), server_ip varchar(15), event_time datetime, lead_id int, campaign_id varchar(20), pause_epoch int,
  pause_sec int, wait_epoch int, wait_sec int, talk_epoch int, talk_sec int, dispo_epoch int, dispo_sec int, status varchar(6), user_group varchar(20), comments varchar(20), sub_status varchar(6),
  dead_epoch int, dead_sec int, processed enum('Y','N'), uniqueid varchar(20), pause_type varchar(10))""")
now = int(time.time())
ymd = lambda e: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e))
# inbound: 4 for the demo ingroup, 2 for a group nobody mapped
for i in range(1, 7):
    e = now - 3600 + i * 120
    grp = "demo_support" if i <= 4 else "unknown_grp"
    cur.execute("insert into vicidial_closer_log (lead_id,list_id,campaign_id,call_date,start_epoch,end_epoch,length_in_sec,status,phone_code,phone_number,user,processed,queue_seconds,user_group,term_reason,uniqueid,called_count) values (%s,1,%s,%s,%s,%s,%s,%s,'91',%s,%s,'Y',%s,'AGENTS',%s,%s,1)",
                (100 + i, grp, ymd(e), e, e + 60 + i, 60 + i if i != 3 else 0, "DROP" if i == 3 else "CALLBK", f"98765432{i:02d}", "1955" if i != 3 else "VDCL", 5.5 * i, "CALLER" if i != 3 else "ABANDON", f"1792{i:06d}.{i}"))
# outbound: 3 for the demo campaign, 1 unmapped
for i in range(1, 5):
    e = now - 3000 + i * 150
    camp = "DEMO-RENEW" if i <= 3 else "NO_SUCH_CAMP"
    cur.execute("insert into vicidial_log (uniqueid,lead_id,list_id,campaign_id,call_date,start_epoch,end_epoch,length_in_sec,status,phone_code,phone_number,user,processed,user_group,term_reason,called_count) values (%s,%s,1,%s,%s,%s,%s,%s,'SALE','91',%s,'1955','Y','AGENTS','AGENT',1)",
                (f"1793{i:06d}.{i}", 200 + i, camp, ymd(e), e, e + 90, 90, f"99887766{i:02d}"))
# recordings: the first two outbound calls (vicidial_id = uniqueid) and the first inbound call (vicidial_id = closecallid)
for vid, lead in ((f"1793{1:06d}.1", 201), (f"1793{2:06d}.2", 202), ("1", 101)):
    cur.execute("insert into recording_log (channel,server_ip,start_time,start_epoch,end_epoch,length_in_sec,filename,location,lead_id,user,vicidial_id) values ('SIP/x','10.0.0.5',%s,%s,%s,90,%s,%s,%s,'1955',%s)",
                (ymd(now - 2000), now - 2000, now - 1910, f"rec_{lead}-all.mp3", f"http://10.0.0.5/RECORDINGS/MP3/rec_{lead}-all.mp3", lead, vid))
# agent log for 1955: login pause, work, lunch, tea, work, an extra agent u2 with a custom pause code
rows = [("1955", "LOGIN", 120, 0, 0, 0, 0, "DEMO-RENEW"), ("1955", "", 0, 30, 90, 40, 5, "DEMO-RENEW"), ("1955", "LUNCH", 1800, 0, 0, 0, 0, "DEMO-RENEW"),
        ("1955", "", 0, 20, 300, 60, 0, "DEMO-RENEW"), ("1955", "TEA", 600, 0, 0, 0, 0, "DEMO-RENEW"), ("1955", "", 0, 45, 120, 30, 10, "demo_support"),
        ("u2", "ZZZ", 300, 0, 0, 0, 0, "DEMO-RENEW"), ("u2", "", 0, 60, 400, 100, 0, "DEMO-RENEW"), ("u2", "", 0, 10, 50, 10, 0, "UNMAPPED_CAMP")]
for n, (user, sub, pause, wait, talk, dispo, dead, camp) in enumerate(rows):
    cur.execute("insert into vicidial_agent_log (user,server_ip,event_time,lead_id,campaign_id,pause_sec,wait_sec,talk_sec,dispo_sec,dead_sec,status,user_group,sub_status,uniqueid) values (%s,'10.0.0.5',%s,%s,%s,%s,%s,%s,%s,%s,'SALE','AGENTS',%s,%s)",
                (user, ymd(now - 3300 + n * 200), 200 + n, camp, pause, wait, talk, dispo, dead, sub or None, f"1793{(n % 4) + 1:06d}.{(n % 4) + 1}" if talk else None))
for t in ("vicidial_closer_log", "vicidial_log", "recording_log", "vicidial_agent_log"):
    cur.execute(f"select count(*) from {t}"); print(t, cur.fetchone()[0])
