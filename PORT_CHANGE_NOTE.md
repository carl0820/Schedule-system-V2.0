# Port Change: 8092 → 9092

## Summary

The service port has been changed from **8092** to **9092** due to Windows port reservation conflicts.

## Root Cause

Port 8092 falls within a Windows reserved port range (8052-8151) on this system, likely due to Hyper-V or other Windows services. This caused the following error:

```
ERROR: [Errno 13] error while attempting to bind on address ('0.0.0.0', 8092):
[winerror 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

Translation: "Permission denied - attempted socket access in an unauthorized manner"

## Verification

You can check Windows reserved port ranges on your system:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

On this system, the output showed:
```
Protocol tcp Port Exclusion Ranges
Start Port    End Port
----------    --------
  1128        1227
  4936        5035
  5036        5135
  5141        5240
  5262        5361
  8052        8151  ← Port 8092 is in this range
 50000       50059
```

## Solutions Considered

### Option 1: Change Port (IMPLEMENTED)
✅ Changed service port to 9092 (outside reserved range)
- Simple, reliable solution
- No system changes required
- Works immediately

### Option 2: Exclude Port from Reservation (NOT IMPLEMENTED)
❌ Use netsh command to remove port from reserved range
```powershell
# Requires Administrator privileges
netsh int ipv4 add excludedportrange protocol=tcp startport=8092 numberofports=1
```
- Requires Administrator access
- System-level change
- May conflict with Hyper-V/Windows services
- Not recommended

## Files Updated

All configuration and startup scripts have been updated to use port 9092:

- `config.py` - PORT = 9092
- `start.ps1` - Port checks and URLs updated
- `start_safe.ps1` - Port checks and URLs updated
- `restart_service.ps1` - Reads PORT from config.py (automatically updated)
- `diagnose.ps1` - Diagnostic checks updated to port 9092
- `check_port_reservation.ps1` - Diagnostic tool for checking reserved ranges

## New Service URLs

After starting the service, access it at:

- **Homepage**: http://localhost:9092
- **API Docs**: http://localhost:9092/docs
- **Robot List**: http://localhost:9092/static/robot_list.html
- **Task List**: http://localhost:9092/static/task_list.html
- **Map Management**: http://localhost:9092/static/map_management.html

## Verification

Service is currently running successfully on port 9092:
```powershell
PS> Get-NetTCPConnection -LocalPort 9092 | Select-Object LocalAddress, LocalPort, State, OwningProcess

LocalAddress LocalPort       State OwningProcess
------------ ---------       ----- -------------
127.0.0.1         9092 Established         11340
0.0.0.0           9092      Listen         11340
```

## Recommendation

**Port 9092 is the recommended port for this Windows environment.** It avoids all reserved port conflicts and works reliably.

If you need to use port 8092 for legacy reasons, you must either:
1. Remove Hyper-V (if not needed)
2. Use the netsh command to exclude port 8092 from reservation (requires Admin)
3. Contact your system administrator

---

**Date**: 2025-12-29
**Status**: ✅ RESOLVED - Service running on port 9092
