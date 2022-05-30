<h2 align="center">
  FastAPI-Scheduler
</h2>

## 项目介绍

`FastAPI-Scheduler`是一个基于`APScheduler`的简单定时任务管理`FastAPI`拓展库.

## 安装

```bash
pip install fastapi-scheduler
```

## 简单示例

**main.py**:

```python
from fastapi import FastAPI
from fastapi_amis_admin.amis_admin.settings import Settings
from fastapi_amis_admin.amis_admin.site import AdminSite
from datetime import date
from fastapi_scheduler import SchedulerAdmin

# 创建`FastAPI`应用
app = FastAPI()

# 创建`AdminSite`实例
site = AdminSite(settings=Settings(database_url_async='sqlite+aiosqlite:///amisadmin.db'))

# # 自定义定时任务调度器
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from apscheduler.jobstores.redis import RedisJobStore
# # 使用`RedisJobStore`创建任务存储
# scheduler = AsyncIOScheduler(jobstores={'default':RedisJobStore(db=2,host="127.0.0.1",port=6379,password="test")})
# scheduler = SchedulerAdmin.bind(site,scheduler=scheduler)

# 创建定时任务调度器`SchedulerAdmin`实例
scheduler = SchedulerAdmin.bind(site)


# 添加定时任务,参考官方文档: https://apscheduler.readthedocs.io/en/master/
# use when you want to run the job at fixed intervals of time
@scheduler.scheduled_job('interval', seconds=60)
def interval_task_test():
    print('interval task is run...')


# use when you want to run the job periodically at certain time(s) of day
@scheduler.scheduled_job('cron', hour=3, minute=30)
def cron_task_test():
    print('cron task is run...')


# use when you want to run the job just once at a certain point of time
@scheduler.scheduled_job('date', run_date=date(2022, 11, 11))
def date_task_test():
    print('date task is run...')


# 挂载后台管理系统
site.mount_app(app)


@app.on_event("startup")
async def startup():
    # 启动定时任务调度器
    scheduler.start()


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, debug=True)
```
## 界面预览

- Open `http://127.0.0.1:8000/admin/` in your browser:

![SchedulerAdmin](https://s2.loli.net/2022/05/10/QEtCLsWi1389BKH.png)

## 依赖项目

- [FastAPI-Amis-Admin](https://docs.amis.work/)

- [APScheduler](https://apscheduler.readthedocs.io/en/master/)

## 许可协议

该项目遵循 Apache2.0 许可协议。
