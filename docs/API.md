### 5.1 思岚科技底盘API集成
- **机器人状态获取**：位置、姿态、速度、电量
- **运动控制**：速度指令、目标点导航
- **传感器数据**：激光雷达、里程计等（如有）

1.获取机器人位置坐标：
http://10.160.128.91:1448/api/core/slam/v1/localization/pose
{
  "pitch": 0,
  "roll": 0,
  "x": 0.26705364791840003,
  "y": 0.04228994971557916,
  "yaw": -0.02706552307438015,
  "z": 0
}
2.获取机器人速度
http://10.160.128.91:1448/api/core/motion/v1/speed
{
  "omega": 0,
  "vx": 0,
  "vy": 0
}
3.获取电量
http://10.160.128.91:1448/api/core/system/v1/power/status
{
  "batteryPercentage": 100,
  "dockingStatus": "on_dock",
  "isCharging": false,
  "isDCConnected": false,
  "powerStage": "running",
  "sleepMode": "awake"
}
4.获取设备健康状态
http://10.160.128.91:1448/api/core/system/v1/robot/health
{
  "baseError": [
    {
      "component": 1,
      "componentErrorCode": 2304,
      "componentErrorDeviceId": -1,
      "componentErrorType": 2057,
      "errorCode": 33622272,
      "id": 0,
      "level": 2,
      "message": "Low localization quality"
    }
  ],
  "hasDepthCameraDisconnected": false,
  "hasError": true,
  "hasFatal": false,
  "hasLidarDisconnected": false,
  "hasSdpDisconnected": false,
  "hasSystemEmergencyStop": false,
  "hasWarning": false
}
5.获取设备信息SN以及固件版本
http://10.160.128.91:1448/api/core/system/v1/robot/info
{
  "configurationVersion": "",
  "deviceID": "E69AFEC8CEC906A9E16BC1BD43554245",
  "device_id": "e69afec8-cec9-06a9-e16b-c1bd43554245",
  "hardwareVersion": "7.0",
  "manufacturerId": 255,
  "manufacturerName": "Slamtec",
  "modelId": 1013,
  "modelName": "Hermes",
  "softwareVersion": "6.2.2-rtm-3588+20250701"
}
6.获取定位质量
http://10.160.128.91:1448/api/core/slam/v1/localization/quality
{
    34
}

7. 创建运动行为
http://10.160.128.91:1448/api/core/motion/v1/actions
{
  "action_name": "slamtec.agent.actions.MoveToAction",
  "options": {
    "target": {
      "x": 0,
      "y": 0,
      "z": 0
    },
    "move_options": {
      "mode": 0,
      "flags": [],
      "yaw": 0,
      "acceptable_precision": 0,
      "fail_retry_count": 0,
      "speed_ratio": 0
    }
  }
}

响应：
{
  "action_id": 2,
  "action_name": "slamtec.agent.actions.MoveToAction",
  "stage": "",
  "state": {
    "reason": "", #如果 result 是-1，则该字段表示失败的原因
    "result": 0, #0:Success, -1: Failed, -2: Aborted
    "status": 0 # 0:NewBorn, 1:Working, 3:Paused, 4:Done
  }
}
8. 同步地图
  - `POST /api/multi-floor/map/v1/stcm/:sync` - 同步地图
Request Body: {}
Response: 200 OK
9. 回桩
  - `POST /api/multi-floor/motion/v1/gohomeaction` - 回桩
   Response Body： {}
   响应：{
    "action_id": 22,
    "action_name": "slamtec.agent.actions.MultiFloorBackHomeAction",
    "stage": "INITIALIZING",
    "state": {
        "reason": "",
        "result": 0,
        "status": 0
    }
}
10.  查询action的状态
- `GET /api/core/motion/v1/actions/{action_id}` - 查询action的状态
  Response Body： {}
  响应：{
    "action_id": 24,
    "state": {
        "reason": "",
        "result": 0,
        "status": 4
    }
}
11.查询当前任务状态
- `GET /api/core/motion/v1/actions/:current` - 查询当前任务状态
响应：
{
  "action_id": 0,
  "action_name": "string",
  "stage": "GOING_TO_TARGET",
  "state": {
    "status": 0,
    "result": 0,
    "reason": ""
  }
}
12. 通过POI的方式移动到点的命令
- `POST /api/core/motion/v1/actions` - 通过POI 精确移动到点
Response Body：{
    "action_name": "slamtec.agent.actions.MultiFloorMoveAction",
    "options": {
        "target": {
            "poi_name": "P01"
        },
        "move_options": {
            "mode": 0,  //0(Free navigation mode, suggestted)、1(Strict Track Model)、2(Track priority mode)
            "flags": [
                "precise",  //Reaching the target point precisely
                "with_yaw"   //Move to specified yaw
            ],
            "acceptable_precision": 0.5, //To point error range
            "fail_retry_count": 0
        }
    }
}
响应：{
  "action_id": 41,
  "action_name": "slamtec.agent.actions.MultiFloorMoveAction",
  "stage": "INITIALIZING",
  "state": {
    "reason": "",
    "result": 0,
    "status": 0
  }
}
12. 创建一个POI的任务点
- `POST /api/core/artifact/v1/pois` - 创建当前点POI
Response Body：{
    "id": "e77857db-673d-4b13-aae6-fc089eb24bce",
    "metadata": {
      "display_name": "X10"
    }
  }

响应：true
13.获取IMU信息
http://10.160.128.91:1448/api/core/slam/v1/imu
{
  "acc": {
    "x": 0.010999999940395355,
    "y": -0.04100000113248825,
    "z": 0.03400000184774399
  },
  "availibilityBitMap": 643,
  "compass": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "euler_angle": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "gyro": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "quaternion": {
    "w": 1,
    "x": 0,
    "y": 0,
    "z": 0
  },
  "raw_acc": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "raw_compass": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "raw_gyro": {
    "x": 0,
    "y": 0,
    "z": 0
  },
  "timestamp": 945140
}
14.获取里程计位姿
http://10.160.128.91:1448/api/core/slam/v1/localization/odopose
响应：
{
  "pitch": 0,
  "roll": 0,
  "x": 0.00004779998926096596,
  "y": 7.908959598346144e-9,
  "yaw": -0.0001989675365621224,
  "z": 0
}
15. 获取激光雷达数据
/api/core/system/v1/laserscan
响应：
{
  "pose": {
    "x": 0,
    "y": 0,
    "z": 0,
    "yaw": 0,
    "picth": 0,
    "roll": 0
  },
  "laser_points": [
    {
      "distance": 0,
      "angle": 0,
      "valid": true
    }
  ]
}
16. 取消任务
DELETE  /api/core/motion/v1/actions/:current
返回：200
17. 获取所有POI
http://10.160.128.91:1448/api/multi-floor/map/v1/pois
返回：
17. 获取所有POI
http://10.160.128.91:1448/api/core/artifact/v1/pois
响应：
[
  {
    "id": "18a0bc81-e0ac-4dc3-be99-019bf39aa5c2",
    "metadata": {
      "display_name": "PO1"
    },
    "pose": {
      "x": 3.5,
      "y": -0.64,
      "yaw": -0.75
    }
  }
]

18. 获取虚拟器信息
http://10.160.129.23:1448/api/core/artifact/v1/lines/walls
响应：
[
  {
    "end": {
      "x": 14.072062492370605,
      "y": -0.26947954297065735
    },
    "id": 15,
    "metadata": null,
    "start": {
      "x": 4.321258068084717,
      "y": -0.20910261571407318
    }
  },
  {
    "end": {
      "x": 17.09088897705078,
      "y": 1.1191798448562622
    },
    "id": 16,
    "metadata": null,
    "start": {
      "x": 9.000438690185547,
      "y": 1.33049738407135
    }
  },
  {
    "end": {
      "x": 10.147592544555664,
      "y": -10.382543563842773
    },
    "id": 17,
    "metadata": null,
    "start": {
      "x": 10.238155364990234,
      "y": -0.11853855848312378
    }
  }
]
19. 根据acion_id 查询任务完成状态
http://10.160.128.150:1448/api/core/motion/v1/actions/4526
响应：
{
  "action_id": 4526,
  "state": {
    "reason": "",
    "result": 0,
    "status": 4
  }
}