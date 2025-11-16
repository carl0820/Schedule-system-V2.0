# Release v1.2.0

**Release Date:** 2025-11-16

## 🎉 Features

### Enhanced Multi-Action Task API
- Added comprehensive examples in Swagger UI documentation
- 3 ready-to-use example requests:
  - Move to coordinates and wait (recommended)
  - Move to POI and wait
  - Complete multi-action task (move → wait → move → go home)

### Service Management Scripts
- **start_service.ps1**: Start the robot scheduling service
- **stop_service.ps1**: Stop the service gracefully
- **restart_service.ps1**: Restart the service quickly
- All scripts support background mode and automatic virtual environment detection

## 🐛 Bug Fixes

### API Error Handling
- **Fixed**: `name 'time' is not defined` error in task creation API
  - Moved `time` module import to top-level in `task_scheduler.py` and `tasks.py`
  - Added `start_time` initialization in `create_task` method
  
- **Fixed**: `cannot access local variable 'logger' where it is not associated with a value`
  - Removed redundant `logger` redefinition in exception handler
  - Now uses global logger consistently

### Code Quality
- Removed redundant `import asyncio` statements from `robot_agent.py`
- Improved error messages and logging

## 📚 Documentation

### API Documentation
- Enhanced Swagger UI documentation for `/api/tasks/multi-action` endpoint
- Added detailed usage instructions and best practices
- Clear guidance on when to use `target_pose` vs `poi_name`
- Warning about `POI_NOT_FOUND` errors and how to avoid them

### Service Management
- Added `docs/SERVICE_SCRIPTS.md` with comprehensive usage guide
- Examples for all service management scenarios
- Troubleshooting guide

## 🔧 Technical Improvements

### Code Organization
- Consistent import statements at module level
- Better error handling in API endpoints
- Improved validation and error messages

### API Response
- Ensured `task_id` is always returned in task creation responses
- Added explicit validation to prevent missing `task_id` errors
- Better error messages for debugging

## 📝 Migration Notes

### For API Users
- **No breaking changes**: All existing API calls will continue to work
- **New examples available**: Check Swagger UI at `/docs` for ready-to-use examples
- **Recommendation**: Use `target_pose` instead of `poi_name` for more reliable navigation

### For Developers
- Service management scripts are now available for easier deployment
- All scripts are in English to avoid encoding issues
- Scripts automatically detect virtual environment

## 🚀 Quick Start

### Using the New Service Scripts

```powershell
# Start service
.\start_service.ps1

# Stop service
.\stop_service.ps1

# Restart service
.\restart_service.ps1
```

### Using Multi-Action Task API

See Swagger UI at `http://localhost:8000/docs` for interactive examples, or use:

```bash
# Example 1: Move to coordinates and wait (recommended)
curl -X POST "http://localhost:8000/api/tasks/multi-action" \
  -H "Content-Type: application/json" \
  -d '{"actions":[{"action_type":"move_to","target_pose":{"x":3.8,"y":-2.9,"z":0,"yaw":0,"pitch":0,"roll":0},"acceptable_precision":0.3,"speed_ratio":1.0},{"action_type":"wait","wait_duration":10.0}],"priority":1}'
```

## 📦 Files Changed

- `app/api/tasks.py` - Enhanced API documentation and error handling
- `app/models/task.py` - Added examples to Pydantic model
- `app/services/task_scheduler.py` - Fixed time import issue
- `app/services/robot_agent.py` - Removed redundant imports
- `start_service.ps1` - New service start script
- `stop_service.ps1` - New service stop script
- `restart_service.ps1` - Updated restart script
- `docs/SERVICE_SCRIPTS.md` - Service management documentation

## 🔗 Links

- **Repository**: https://github.com/carl0820/schedule-system-based-on-REST
- **API Documentation**: http://localhost:8000/docs
- **Service Management Guide**: `docs/SERVICE_SCRIPTS.md`

## 🙏 Acknowledgments

This release focuses on improving developer experience and API reliability. All changes are backward compatible.

