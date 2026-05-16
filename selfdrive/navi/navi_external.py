#!/usr/bin/env python3
import os
import queue
import threading
import time
import subprocess
import re
import json
import select
import socket
import struct

import cereal.messaging as messaging
from common.params import Params
from common.realtime import DT_TRML
from selfdrive.hardware import TICI

import zmq

# OPKR, this is for getting navi data from external device.

APILOT_BROADCAST_PORT = 7708
APILOT_RECEIVE_PORT = 7707
APILOT_SERVICE_MSG_C2 = "APMSERVICE:C2:V1"
APILOT_SERVICE_MSG_C3 = "APMSERVICE:C3:V1"
NDA_BROADCAST_PORT = 2899
NDA_RECEIVE_PORTS = (843, 2843)
NDA_SERVICE_MSG = "EON:ROAD_LIMIT_SERVICE:v1"


def _to_int(value, default=0):
  try:
    if value is None or value == "":
      return default
    return int(float(value))
  except (TypeError, ValueError):
    return default


def _to_float(value, default=0.):
  try:
    if value is None or value == "":
      return default
    return float(value)
  except (TypeError, ValueError):
    return default


def _to_bool(value):
  if isinstance(value, bool):
    return value
  return bool(_to_int(value, 0))


def _get_broadcast_address():
  try:
    import fcntl
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      data = fcntl.ioctl(sock.fileno(), 0x8919, struct.pack("256s", b"wlan0"))
      return socket.inet_ntoa(data[20:24])
  except Exception:
    return "255.255.255.255"


def _apilot_send_discovery(sock, remote_addr=None, include_nda=False, manual_hosts=None):
  broadcast = _get_broadcast_address()
  targets = [
    (APILOT_SERVICE_MSG_C3 if TICI else APILOT_SERVICE_MSG_C2, broadcast, APILOT_BROADCAST_PORT),
  ]

  if include_nda:
    targets.append((NDA_SERVICE_MSG, broadcast, NDA_BROADCAST_PORT))

  if remote_addr is not None:
    targets.append((APILOT_SERVICE_MSG_C3 if TICI else APILOT_SERVICE_MSG_C2, remote_addr[0], APILOT_BROADCAST_PORT))
    if include_nda:
      targets.append((NDA_SERVICE_MSG, remote_addr[0], NDA_BROADCAST_PORT))

  for host in manual_hosts or []:
    targets.append((APILOT_SERVICE_MSG_C3 if TICI else APILOT_SERVICE_MSG_C2, host, APILOT_BROADCAST_PORT))
    if include_nda:
      targets.append((NDA_SERVICE_MSG, host, NDA_BROADCAST_PORT))

  sent = set()
  for msg, host, port in targets:
    target = (host, port)
    if target in sent:
      continue
    sent.add(target)
    try:
      sock.sendto(msg.encode(), target)
    except Exception:
      pass


def _udp_receive_sockets(include_nda=False):
  sockets = []
  ports = [(APILOT_RECEIVE_PORT, "APM UDP")]

  if include_nda:
    ports.extend((port, "NDA UDP") for port in NDA_RECEIVE_PORTS)

  last_exception = None
  for port, protocol in ports:
    try:
      recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      recv_sock.bind(('0.0.0.0', port))
      recv_sock.setblocking(False)
      sockets.append((recv_sock, protocol, port))
    except Exception as e:
      last_exception = e
      try:
        recv_sock.close()
      except Exception:
        pass

  if not sockets and last_exception is not None:
    raise last_exception

  return sockets


def _apilot_publish(pm, data, opkr_debug=False):
  navi_msg = messaging.new_message('liveENaviData')
  navi_msg.liveENaviData.speedLimit = _to_int(data.get("speedLimit"))
  navi_msg.liveENaviData.safetyDistance = _to_float(data.get("safetyDistance"))
  navi_msg.liveENaviData.safetySign = _to_int(data.get("safetySign"))
  navi_msg.liveENaviData.turnInfo = _to_int(data.get("turnInfo"))
  navi_msg.liveENaviData.distanceToTurn = _to_float(data.get("distanceToTurn"))
  navi_msg.liveENaviData.connectionAlive = _to_bool(data.get("connectionAlive"))
  navi_msg.liveENaviData.roadLimitSpeed = _to_int(data.get("roadLimitSpeed"))
  navi_msg.liveENaviData.linkLength = _to_int(data.get("linkLength"))
  navi_msg.liveENaviData.currentLinkAngle = _to_int(data.get("currentLinkAngle"))
  navi_msg.liveENaviData.nextLinkAngle = _to_int(data.get("nextLinkAngle"))
  navi_msg.liveENaviData.roadName = str(data.get("roadName") or "")
  navi_msg.liveENaviData.isHighway = _to_bool(data.get("isHighway"))
  navi_msg.liveENaviData.isTunnel = _to_bool(data.get("isTunnel"))

  if opkr_debug:
    navi_msg.liveENaviData.opkr0 = str(data.get("opkr0") or "")
    navi_msg.liveENaviData.opkr1 = str(data.get("opkr1") or "")
    navi_msg.liveENaviData.opkr2 = str(data.get("opkr2") or "")
    navi_msg.liveENaviData.opkr3 = str(data.get("opkr3") or "")
    navi_msg.liveENaviData.opkr4 = str(data.get("opkr4") or "")
    navi_msg.liveENaviData.opkr5 = str(data.get("opkr5") or "")
    navi_msg.liveENaviData.opkr6 = str(data.get("opkr6") or "")
    navi_msg.liveENaviData.opkr7 = str(data.get("opkr7") or "")
    navi_msg.liveENaviData.opkr8 = str(data.get("opkr8") or "")
    navi_msg.liveENaviData.opkr9 = str(data.get("opkr9") or "")

  pm.send('liveENaviData', navi_msg)


def _apilot_handle_json(payload, state):
  if "active" in payload:
    state["active"] = _to_int(payload.get("active"))

  road_limit = payload.get("road_limit")
  if isinstance(road_limit, dict):
    state["roadLimitSpeed"] = _to_int(road_limit.get("road_limit_speed"), state["roadLimitSpeed"])
    state["isHighway"] = _to_bool(road_limit.get("is_highway"))

    cam_speed = _to_int(road_limit.get("cam_limit_speed"), 0)
    cam_dist = _to_float(road_limit.get("cam_limit_speed_left_dist"), 0.)
    if cam_speed > 0:
      state["speedLimit"] = cam_speed
    if cam_dist > 0:
      state["safetyDistance"] = cam_dist

    cam_type = _to_int(road_limit.get("cam_type"), 0)
    if cam_type > 0:
      state["safetySign"] = cam_type

  apilot = payload.get("apilot")
  if isinstance(apilot, dict):
    atype = str(apilot.get("type") or "")
    value = apilot.get("value")

    if atype == "opkrturninfo":
      state["turnInfo"] = _to_int(value)
    elif atype == "opkrdistancetoturn":
      state["distanceToTurn"] = _to_float(value)
    elif atype in ("opkrspddist", "opkr-spddist"):
      state["safetyDistance"] = _to_float(value)
    elif atype in ("opkrspdlimit", "opkr-spdlimit"):
      state["speedLimit"] = _to_int(value)
    elif atype in ("opkrsigntype", "opkr-signtype", "opkrroadsigntype"):
      state["safetySign"] = _to_int(value)
    elif atype in ("opkrroadlimitspeed", "opkrroadlimitspd", "opkrwazeroadspdlimit"):
      state["roadLimitSpeed"] = _to_int(value)
    elif atype in ("opkrroadname", "opkrwazeroadname"):
      state["roadName"] = str(value or "")

    n_sdi_type = _to_int(apilot.get("nSdiType"), -1)
    n_sdi_dist = _to_float(apilot.get("nSdiDist"), -1.)
    n_sdi_speed_limit = _to_int(apilot.get("nSdiSpeedLimit"), -1)
    n_sdi_plus_type = _to_int(apilot.get("nSdiPlusType"), -1)
    n_sdi_plus_dist = _to_float(apilot.get("nSdiPlusDist"), -1.)
    n_sdi_plus_speed_limit = _to_int(apilot.get("nSdiPlusSpeedLimit"), -1)
    n_sdi_block_dist = _to_float(apilot.get("nSdiBlockDist"), -1.)

    if n_sdi_type in (0, 1, 2, 3, 4, 8) and n_sdi_speed_limit > 0:
      state["speedLimit"] = n_sdi_speed_limit
      sdi_dist = n_sdi_block_dist if n_sdi_type == 4 and n_sdi_block_dist > 0 else n_sdi_dist
      if sdi_dist > 0:
        state["safetyDistance"] = sdi_dist
      state["safetySign"] = n_sdi_type
    elif n_sdi_plus_type == 22 or n_sdi_type == 22:
      state["speedLimit"] = 35
      bump_dist = n_sdi_plus_dist if n_sdi_plus_type == 22 else n_sdi_dist
      if bump_dist > 0:
        state["safetyDistance"] = bump_dist
      state["safetySign"] = 22
    elif n_sdi_plus_speed_limit > 0 and n_sdi_plus_dist > 0:
      state["speedLimit"] = n_sdi_plus_speed_limit
      state["safetyDistance"] = n_sdi_plus_dist
      state["safetySign"] = n_sdi_plus_type

    if n_sdi_type == 24 or n_sdi_plus_type == 24:
      state["isTunnel"] = True

    for key in ("nRoadLimitSpeed", "nSdiSpeedLimit", "nSdiDist", "nTBTTurnType", "nTBTDist", "szPosRoadName"):
      if key in apilot:
        if key == "nRoadLimitSpeed":
          road_speed = _to_int(apilot.get(key), 0)
          if road_speed >= 200:
            road_speed = int((road_speed - 20) / 10)
          if road_speed > 0:
            state["roadLimitSpeed"] = road_speed
        elif key == "nSdiSpeedLimit" and _to_int(apilot.get(key), -1) > 0:
          state["speedLimit"] = _to_int(apilot.get(key))
        elif key == "nSdiDist" and _to_float(apilot.get(key), -1.) > 0:
          state["safetyDistance"] = _to_float(apilot.get(key))
        elif key == "nTBTTurnType" and _to_int(apilot.get(key), -1) >= 0:
          state["turnInfo"] = _nda_turn_info(_to_int(apilot.get(key)))
        elif key == "nTBTDist" and _to_float(apilot.get(key), -1.) > 0:
          state["distanceToTurn"] = _to_float(apilot.get(key))
        elif key == "szPosRoadName" and apilot.get(key):
          state["roadName"] = str(apilot.get(key))


def _nda_turn_info(turn_type):
  if turn_type in (12, 16):
    return 1
  if turn_type in (13, 19):
    return 2
  if turn_type in (7, 44, 17, 75, 102, 105, 112, 115, 76, 118):
    return 3
  if turn_type in (6, 43, 73, 74, 101, 104, 111, 114, 123, 124, 117):
    return 4
  if turn_type in (14, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 153, 154, 249):
    return 5
  return 0


def _apilot_udp_navid_thread(end_event, pm, opkr_debug, include_nda=False, manual_hosts=None):
  state = {
    "speedLimit": 0,
    "safetyDistance": 0.,
    "safetySign": 0,
    "turnInfo": 0,
    "distanceToTurn": 0.,
    "connectionAlive": False,
    "roadLimitSpeed": 0,
    "linkLength": 0,
    "currentLinkAngle": 0,
    "nextLinkAngle": 0,
    "roadName": "",
    "isHighway": False,
    "isTunnel": False,
  }

  remote_addr = None
  remote_protocol = "APM UDP"
  last_rx_time = 0.
  last_broadcast_time = 0.
  last_gps_time = 0.
  last_publish_time = 0.
  request_gps = False

  gps_sm = messaging.SubMaster(['gpsLocationExternal'], poll=['gpsLocationExternal'])

  recv_socks = _udp_receive_sockets(include_nda)

  send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

  try:
    while not end_event.is_set():
      now = time.monotonic()

      if now - last_broadcast_time > 5.:
        _apilot_send_discovery(send_sock, remote_addr, include_nda, manual_hosts)
        last_broadcast_time = now

      try:
        ready, _, _ = select.select([sock for sock, _, _ in recv_socks], [], [], DT_TRML)
      except Exception:
        ready = []

      for ready_sock in ready:
        try:
          protocol = next((protocol for sock, protocol, _ in recv_socks if sock == ready_sock), "APM UDP")
          raw, remote_addr = ready_sock.recvfrom(4096)
          remote_protocol = protocol
          payload = json.loads(raw.decode())

          if payload.get("request_gps") == 1:
            request_gps = True
          elif payload.get("request_gps") == 0:
            request_gps = False

          if "echo" in payload and remote_addr is not None:
            try:
              port = NDA_BROADCAST_PORT if remote_protocol == "NDA UDP" else APILOT_BROADCAST_PORT
              send_sock.sendto(json.dumps(payload["echo"]).encode(), (remote_addr[0], port))
            except Exception:
              pass

          _apilot_handle_json(payload, state)
          state["connectionAlive"] = True
          last_rx_time = now

          if opkr_debug:
            state["opkr0"] = remote_protocol
            state["opkr1"] = f"{remote_addr[0]}:{remote_addr[1]}" if remote_addr else ""
            state["opkr2"] = f"SL:{state['speedLimit']} DS:{int(state['safetyDistance'])}"
            state["opkr3"] = f"RS:{state['roadLimitSpeed']}"
            state["opkr4"] = str(state["roadName"])
        except Exception as e:
          if opkr_debug:
            state["opkr0"] = "APM UDP parse error"
            state["opkr1"] = str(e)

      if request_gps and remote_addr is not None and now - last_gps_time > 1.:
        try:
          gps_sm.update(0)
          location = gps_sm['gpsLocationExternal']
          if location.accuracy < 10.:
            json_location = json.dumps({"location": [
              location.latitude,
              location.longitude,
              location.altitude,
              location.speed,
              location.bearingDeg,
              location.accuracy,
              location.timestamp,
              location.verticalAccuracy,
              location.bearingAccuracyDeg,
              location.speedAccuracy,
            ]})
            port = NDA_BROADCAST_PORT if remote_protocol == "NDA UDP" else APILOT_BROADCAST_PORT
            send_sock.sendto(json_location.encode(), (remote_addr[0], port))
        except Exception:
          request_gps = False
        last_gps_time = now

      if now - last_rx_time > 6.:
        state["connectionAlive"] = False
        state["speedLimit"] = 0
        state["safetyDistance"] = 0.
        state["safetySign"] = 0
        state["turnInfo"] = 0
        state["distanceToTurn"] = 0.
        state["roadLimitSpeed"] = 0
        state["roadName"] = ""
        state["isHighway"] = False
        state["isTunnel"] = False

      if now - last_publish_time > DT_TRML:
        _apilot_publish(pm, state, opkr_debug)
        last_publish_time = now
  finally:
    for recv_sock, _, _ in recv_socks:
      recv_sock.close()
    send_sock.close()

def navid_thread(end_event, nv_queue):
  pm = messaging.PubMaster(['liveENaviData'])
  count = 0

  spd_limit = 0
  safety_distance = 0
  sign_type = 0
  turn_info = 0
  turn_distance = 0
  road_limit_speed = 0
  link_length = 0
  current_link_angle = 0
  next_link_angle = 0
  road_name = ""
  is_highway = 0
  is_tunnel = 0

  OPKR_Debug = Params().get_bool("OPKRDebug")
  if OPKR_Debug:
    opkr_0 = ""
    opkr_1 = ""
    opkr_2 = ""
    opkr_3 = ""
    opkr_4 = ""
    opkr_5 = ""
    opkr_6 = ""
    opkr_7 = ""
    opkr_8 = ""
    opkr_9 = ""


  ip_add = ""
  ip_bind = False
 
  check_connection = False
  external_device_ip = Params().get("ExternalDeviceIP", encoding="utf8") or ""
  ip_count = max(1, len([ip for ip in external_device_ip.split(',') if ip.strip()]))
  is_metric = Params().get_bool("IsMetric")
  navi_selection = int(Params().get("OPKRNaviSelect", encoding="utf8"))

  if navi_selection == 6:
    manual_hosts = [ip.strip() for ip in external_device_ip.split(',') if ip.strip()]
    ip_now = Params().get("ExternalDeviceIPNow", encoding="utf8")
    if ip_now and ip_now.strip() not in manual_hosts:
      ip_now = ip_now.strip()
      manual_hosts.append(ip_now)
    _apilot_udp_navid_thread(end_event, pm, OPKR_Debug, include_nda=True, manual_hosts=manual_hosts)
    return

  mtom3 = False
  mtom2 = False
  mtom1 = False
  mtom_dist_last = 0

  if navi_selection == 5:
    waze_alert_id = 0
    waze_alert_distance = "0"
    waze_road_speed_limit = 0
    waze_current_speed = 0
    waze_road_name = ""
    waze_nav_sign = 0
    waze_nav_distance = 0
    waze_alert_type = ""
    waze_is_metric = Params().get_bool("IsMetric")
    waze_current_speed_prev = 0

  while not end_event.is_set():
    if not ip_bind:
      if (count % int(max(60., ip_count) / DT_TRML)) == 0:
        os.system("/data/openpilot/selfdrive/assets/addon/script/find_ip.sh &")
      if (count % int((63+ip_count) / DT_TRML)) == 0:
        ip_add = Params().get("ExternalDeviceIPNow", encoding="utf8")
        if ip_add is not None:
          ip_bind = True
          check_connection = True

    if ip_bind:
      spd_limit = 0
      safety_distance = 0
      sign_type = 0
      turn_info = 0
      turn_distance = 0
      road_limit_speed = 0
      link_length = 0
      current_link_angle = 0
      next_link_angle = 0
      road_name = ""
      is_highway = 0
      is_tunnel = 0

      if navi_selection == 5:
        if (count % int(10. / DT_TRML)) == 0 and int(waze_current_speed) > 2:
          waze_alert_id = 0
          waze_alert_distance = "0"
          waze_alert_type = ""
        if (count % int(10. / DT_TRML)) == 0 and int(waze_current_speed) > 2 and int(waze_nav_distance) < 30:
          waze_nav_sign = 0
          waze_nav_distance = 0
        waze_current_speed = 0

      if OPKR_Debug:
        opkr_0 = ""
        opkr_1 = ""
        opkr_2 = ""
        opkr_3 = ""
        opkr_4 = ""
        opkr_5 = ""
        opkr_6 = ""
        opkr_7 = ""
        opkr_8 = ""
        opkr_9 = ""

      context = zmq.Context()
      socket = context.socket(zmq.SUB)

      try:
        socket.connect("tcp://" + str(ip_add) + ":5555")
      except:
        socket.connect("tcp://127.0.0.1:5555")
        pass
      socket.subscribe("")

      message = str(socket.recv(), 'utf-8')

      if (count % int(30. / DT_TRML)) == 0:
        try:
          rtext = subprocess.check_output(["netstat", "-tp"])
          check_connection = True if str(rtext).find('navi') else False
        except:
          pass
      
      for line in message.split('\n'):
        if "opkrspdlimit" in line:
          arr = line.split('opkrspdlimit: ')
          spd_limit = arr[1]
        if "opkrspddist" in line:
          arr = line.split('opkrspddist: ')
          safety_distance = arr[1]
        if "opkrsigntype" in line:
          arr = line.split('opkrsigntype: ')
          sign_type = arr[1]
        if "opkrturninfo" in line:
          arr = line.split('opkrturninfo: ')
          turn_info = arr[1]
        if "opkrdistancetoturn" in line:
          arr = line.split('opkrdistancetoturn: ')
          turn_distance = arr[1]
        if "opkrroadlimitspd" in line:
          arr = line.split('opkrroadlimitspd: ')
          road_limit_speed = arr[1]
        if "opkrlinklength" in line:
          arr = line.split('opkrlinklength: ')
          link_length = arr[1]
        if "opkrcurrentlinkangle" in line:
          arr = line.split('opkrcurrentlinkangle: ')
          current_link_angle = arr[1]
        if "opkrnextlinkangle" in line:
          arr = line.split('opkrnextlinkangle: ')
          next_link_angle = arr[1]
        if "opkrroadname" in line:
          arr = line.split('opkrroadname: ')
          road_name = arr[1]
        if "opkrishighway" in line:
          arr = line.split('opkrishighway: ')
          is_highway = arr[1]
        if "opkristunnel" in line:
          arr = line.split('opkristunnel: ')
          is_tunnel = arr[1]
        if navi_selection == 5: # NAV unit should be metric. Do not use miles unit.(Distance factor is not detailed.)
          if "opkrwazereportid" in line:
            arr = line.split('opkrwazereportid: ')
            try:
              waze_alert_type = arr[1]
              if "icon_report_speedlimit" in arr[1]:
                waze_alert_id = 1
              elif "icon_report_camera" in arr[1]:
                waze_alert_id = 1
              elif "icon_report_speedcam" in arr[1]:
                waze_alert_id = 1
              elif "icon_report_police" in arr[1]:
                waze_alert_id = 2
              elif "icon_report_hazard" in arr[1]:
                waze_alert_id = 3
              elif "icon_report_traffic" in arr[1]:
                waze_alert_id = 4
            except:
              pass
          if "opkrwazealertdist" in line:
            arr = line.split('opkrwazealertdist: ')
            try:
              if arr[1] is None or arr[1] == "":
                waze_alert_distance = "0"
              else:
                waze_alert_distance = str(re.sub(r'[^0-9]', '', arr[1]))
            except:
              pass
          if "opkrwazeroadspdlimit" in line:
            arr = line.split('opkrwazeroadspdlimit: ')
            try:
              if arr[1] == "-1":
                waze_road_speed_limit = 0
              elif arr[1] is None or arr[1] == "":
                waze_road_speed_limit = 0
              else:
                waze_road_speed_limit = arr[1]
            except:
              waze_road_speed_limit = 0
              pass
          if "opkrwazecurrentspd" in line:
            arr = line.split('opkrwazecurrentspd: ')
            try:
              waze_current_speed = arr[1]
            except:
              pass
          if "opkrwazeroadname" in line: # route should be set.
            arr = line.split('opkrwazeroadname: ')
            try:
              waze_road_name = arr[1]
            except:
              pass
          if "opkrwazenavsign" in line: # route should be set.
            arr = line.split('opkrwazenavsign: ')
            try:
              waze_nav_sign = arr[1]
            except:
              pass
          if "opkrwazenavdist" in line: # route should be set.
            arr = line.split('opkrwazenavdist: ')
            try:
              waze_nav_distance = arr[1]
            except:
              pass

        if OPKR_Debug:
          try:
            if "opkr0" in line:
              arr = line.split('opkr0   : ')
              opkr_0 = arr[1]
          except:
            pass
          try:
            if "opkr1" in line:
              arr = line.split('opkr1   : ')
              opkr_1 = arr[1]
          except:
            pass
          try:
            if "opkr2" in line:
              arr = line.split('opkr2   : ')
              opkr_2 = arr[1]
          except:
            pass
          try:
            if "opkr3" in line:
              arr = line.split('opkr3   : ')
              opkr_3 = arr[1]
          except:
            pass
          try:
            if "opkr4" in line:
              arr = line.split('opkr4   : ')
              opkr_4 = arr[1]
          except:
            pass
          try:
            if "opkr5" in line:
              arr = line.split('opkr5   : ')
              opkr_5 = arr[1]
          except:
            pass
          try:
            if "opkr6" in line:
              arr = line.split('opkr6   : ')
              opkr_6 = arr[1]
          except:
            pass
          try:
            if "opkr7" in line:
              arr = line.split('opkr7   : ')
              opkr_7 = arr[1]
          except:
            pass
          try:
            if "opkr8" in line:
              arr = line.split('opkr8   : ')
              opkr_8 = arr[1]
          except:
            pass
          try:
            if "opkr9" in line:
              arr = line.split('opkr9   : ')
              opkr_9 = arr[1]
          except:
            pass

      navi_msg = messaging.new_message('liveENaviData')
      navi_msg.liveENaviData.speedLimit = int(spd_limit)
      navi_msg.liveENaviData.safetyDistance = float(safety_distance)
      navi_msg.liveENaviData.safetySign = int(sign_type)
      navi_msg.liveENaviData.turnInfo = int(turn_info)
      navi_msg.liveENaviData.distanceToTurn = float(turn_distance)
      navi_msg.liveENaviData.connectionAlive = bool(check_connection)
      navi_msg.liveENaviData.roadLimitSpeed = int(road_limit_speed)
      navi_msg.liveENaviData.linkLength = int(link_length)
      navi_msg.liveENaviData.currentLinkAngle = int(current_link_angle)
      navi_msg.liveENaviData.nextLinkAngle = int(next_link_angle)
      navi_msg.liveENaviData.roadName = str(road_name)
      navi_msg.liveENaviData.isHighway = bool(int(is_highway))
      navi_msg.liveENaviData.isTunnel = bool(int(is_tunnel))

      if OPKR_Debug:
        navi_msg.liveENaviData.opkr0 = str(opkr_0)
        navi_msg.liveENaviData.opkr1 = str(opkr_1)
        navi_msg.liveENaviData.opkr2 = str(opkr_2)
        navi_msg.liveENaviData.opkr3 = str(opkr_3)
        navi_msg.liveENaviData.opkr4 = str(opkr_4)
        navi_msg.liveENaviData.opkr5 = str(opkr_5)
        navi_msg.liveENaviData.opkr6 = str(opkr_6)
        navi_msg.liveENaviData.opkr7 = str(opkr_7)
        navi_msg.liveENaviData.opkr8 = str(opkr_8)
        navi_msg.liveENaviData.opkr9 = str(opkr_9)

      if navi_selection == 5:
        navi_msg.liveENaviData.wazeAlertId = int(waze_alert_id)

        if waze_is_metric:
          navi_msg.liveENaviData.wazeAlertDistance = int(waze_alert_distance)
        else:
          if waze_alert_distance == "0":
            mtom1 = False
            mtom2 = False
            mtom3 = False
            navi_msg.liveENaviData.wazeAlertDistance = 0
            mtom_dist_last = 0
            waze_current_speed_prev = 0
          elif len(waze_alert_distance) in (1,2,3) and waze_alert_distance[0] != '0':
            navi_msg.liveENaviData.wazeAlertDistance = round(int(waze_alert_distance) / 3.281)
          elif int(waze_current_speed) == 0:
            navi_msg.liveENaviData.wazeAlertDistance = mtom_dist_last
          elif mtom1 and (count % int(1. / DT_TRML)) == 0:
            navi_msg.liveENaviData.wazeAlertDistance = max(152, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            mtom_dist_last = max(152, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            waze_current_speed_prev = int(waze_current_speed)
          elif waze_alert_distance == "01" and not mtom1:
            waze_current_speed_prev = int(waze_current_speed)
            mtom1 = True
            mtom2 = False
            mtom3 = False
            count = 0
            navi_msg.liveENaviData.wazeAlertDistance = 225
            mtom_dist_last = 225
          elif mtom2 and (count % int(1. / DT_TRML)) == 0:
            navi_msg.liveENaviData.wazeAlertDistance = max(225, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            mtom_dist_last = max(225, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            waze_current_speed_prev = int(waze_current_speed)
          elif waze_alert_distance == "02" and not mtom2:
            waze_current_speed_prev = int(waze_current_speed)
            mtom1 = False
            mtom2 = True
            mtom3 = False
            count = 0
            navi_msg.liveENaviData.wazeAlertDistance = 386
            mtom_dist_last = 386
          elif mtom3 and (count % int(1. / DT_TRML)) == 0:
            navi_msg.liveENaviData.wazeAlertDistance = max(386, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            mtom_dist_last = max(386, round(mtom_dist_last - (((int(waze_current_speed) + waze_current_speed_prev)/2) / 2.237)))
            waze_current_speed_prev = int(waze_current_speed)
          elif waze_alert_distance == "03" and not mtom3:
            waze_current_speed_prev = int(waze_current_speed)
            mtom1 = False
            mtom2 = False
            mtom3 = True
            count = 0
            navi_msg.liveENaviData.wazeAlertDistance = 550
            mtom_dist_last = 550
          else:
            navi_msg.liveENaviData.wazeAlertDistance = mtom_dist_last
        navi_msg.liveENaviData.wazeRoadSpeedLimit = int(waze_road_speed_limit)
        navi_msg.liveENaviData.wazeCurrentSpeed = int(waze_current_speed)
        navi_msg.liveENaviData.wazeRoadName = str(waze_road_name)
        navi_msg.liveENaviData.wazeNavSign = int(waze_nav_sign)
        navi_msg.liveENaviData.wazeNavDistance = int(waze_nav_distance)
        navi_msg.liveENaviData.wazeAlertType = str(waze_alert_type)

      pm.send('liveENaviData', navi_msg)

    count += 1
    time.sleep(DT_TRML)


def main():
  nv_queue = queue.Queue(maxsize=1)
  end_event = threading.Event()

  t = threading.Thread(target=navid_thread, args=(end_event, nv_queue))

  t.start()

  try:
    while True:
      time.sleep(1)
      if not t.is_alive():
        break
  finally:
    end_event.set()

  t.join()


if __name__ == "__main__":
  main()
