from datetime import datetime
from typing import List, Optional, Union, Any, Dict
from fastapi import Body, Depends
from apscheduler.job import Job
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi_amis_admin.amis.components import PageSchema, Page, TableCRUD, TableColumn, Action, ActionType, Dialog, \
    Form, FormItem, InputDatetime
from fastapi_amis_admin.amis.constants import SizeEnum
from fastapi_amis_admin.amis.types import SchemaNode
from fastapi_amis_admin.amis_admin import admin
from fastapi_amis_admin.amis_admin.admin import AdminApp, BaseAdminSite
from fastapi_amis_admin.amis_admin.parser import AmisParser
from fastapi_amis_admin.crud.schema import BaseApiOut, CrudEnum, ItemListSchema
from fastapi_amis_admin.crud.utils import schema_create_by_schema, parser_item_id
from fastapi_amis_admin.models.fields import Field
from pydantic import BaseModel, validator
from pydantic.fields import ModelField
from starlette.requests import Request

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


class SchedulerAdmin(admin.PageAdmin):
    group_schema = None
    page_schema = PageSchema(label='定时任务', icon='fa fa-clock-o')
    page_path = "/amis.json"
    router_prefix = '/jobs'
    scheduler: BaseScheduler = AsyncIOScheduler(
        jobstores={
            'default': MemoryJobStore()
        },
        timezone='Asia/Shanghai',
    )

    class JobModel(BaseModel):
        id: str = Field(..., title="任务ID")
        name: str = Field(..., title="任务名称")
        next_run_time: datetime = Field(
            None,
            title="下次执行时间",
            amis_form_item=InputDatetime(format="YYYY-MM-DDTHH:mm:ss.SSSSSSZ")
        )
        trigger: str = Field(None, title="触发器")  # BaseTrigger
        func_ref: str = Field(..., title="任务函数")
        args: List[Any] = Field(None, title="元组参数", amis_table_column="list")
        kwargs: Dict[str, Any] = Field(None, title="字典参数", amis_table_column="json", amis_form_item="json-editor")
        executor: str = Field("default", title="执行器")
        max_instances: int = Field(None, title="最大并发数量")
        misfire_grace_time: int = Field(None, title="容错时间")
        coalesce: bool = Field(None, title="合并")

        @validator('trigger', pre=True)
        def trigger_valid(cls, v):  # sourcery skip: instance-method-first-arg-name
            return str(v)

        @classmethod
        def parse_job(cls, job: Job):
            return job and cls(**{
                k: getattr(job, k, None)
                for k in cls.__fields__
            })

    @classmethod
    def bind(cls, site: BaseAdminSite, scheduler: BaseScheduler = None) -> BaseScheduler:
        cls.scheduler = scheduler or cls.scheduler
        site.register_admin(cls)
        return cls.scheduler

    def __init__(self, app: "AdminApp"):
        super().__init__(app)
        self.schema_update = schema_create_by_schema(
            self.JobModel, 'JobsUpdate',
            include={"name", "next_run_time"},
            set_none=True
        )

    async def get_page(self, request: Request) -> Page:
        page = await super().get_page(request)
        headerToolbar = ["reload", "bulkActions", {"type": "columns-toggler", "align": "right"},
                         {"type": "drag-toggler", "align": "right"}, {"type": "pagination", "align": "right"},
                         {"type": "tpl", "tpl": "当前有 ${total} 条数据.", "className": "v-middle", "align": "right"}]
        page.body = TableCRUD(
            api=f"get:{self.router_path}/list",
            autoFillHeight=True,
            headerToolbar=headerToolbar,
            filterTogglable=True,
            filterDefaultVisible=False,
            syncLocation=False,
            keepItemSelectionOnPageChange=True,
            footerToolbar=["statistics", "switch-per-page", "pagination", "load-more", "export-csv"],
            columns=await self.get_list_columns(request),
            itemActions=await self.get_actions_on_item(request),
            bulkActions=await self.get_actions_on_bulk(request),
        )
        return page

    async def get_list_columns(self, request: Request) -> List[TableColumn]:
        columns = []
        for modelfield in self.JobModel.__fields__.values():
            form = AmisParser(modelfield).as_table_column()
            if form:
                columns.append(form)
        return columns

    async def get_actions_on_item(self, request: Request) -> List[Action]:
        actions = [
            await self.get_job_action(request, bulk=False, action="resume"),
            await self.get_job_action(request, bulk=False, action="pause"),
            await self.get_update_action(request, bulk=False),
            await self.get_job_action(request, bulk=False, action="remove"),
        ]
        return list(filter(None, actions))

    async def get_actions_on_bulk(self, request: Request) -> List[Action]:
        bulkActions = [
            await self.get_job_action(request, bulk=True, action="resume"),
            await self.get_job_action(request, bulk=True, action="pause"),
            await self.get_job_action(request, bulk=True, action="remove"),
        ]
        return list(filter(None, bulkActions))

    async def get_update_form(self, request: Request, bulk: bool = False) -> Form:
        api = f'{self.router_path}/item/$id'
        fields = self.schema_update.__fields__.values()
        if bulk:
            api = f'{self.router_path}/item/' + '${ids|raw}'
            fields = self.schema_update.__fields__.values()
        return Form(
            api=api,
            name=CrudEnum.update,
            body=[
                await self.get_form_item(request, field, action=CrudEnum.update)
                for field in fields
            ],
            submitText=None,
            trimValues=True,
        )

    async def get_update_action(self, request: Request, bulk: bool = False) -> Optional[Action]:
        return ActionType.Dialog(
            icon='fa fa-pencil',
            tooltip='编辑',
            dialog=Dialog(
                title='编辑',
                size=SizeEnum.lg,
                body=await self.get_update_form(request, bulk=bulk),
            ),
        )

    async def get_job_action(
            self, request: Request,
            bulk: bool = False,
            action: Literal['auto', 'remove', 'pause', 'resume'] = 'remove',
    ) -> Optional[Action]:
        lable, icon = {
            "remove": ("删除", "fa-times text-danger"),
            "pause": ("暂停", "fa-pause"),
            "resume": ("恢复", "fa-play"),
        }[action]
        return ActionType.Ajax(
            icon=f'fa {icon}',
            tooltip=f'批量{lable}',
            confirmText=f'您确定要批量{lable}?',
            api=f"{self.router_path}/item/" + '${ids|raw}?action=' + action,
        ) if bulk else ActionType.Ajax(
            icon=f'fa {icon}',
            tooltip=lable,
            confirmText=f'您确认要{lable}?',
            api=f"{self.router_path}/item/$id?action={action}",
        )

    async def get_form_item(self, request: Request, modelfield: ModelField,
                            action: CrudEnum) -> Union[FormItem, SchemaNode]:
        is_filter = action == CrudEnum.list
        return AmisParser(modelfield).as_form_item(is_filter=is_filter)

    def register_router(self):

        @self.router.get("/list", response_model=BaseApiOut[ItemListSchema[self.JobModel]], include_in_schema=True)
        async def get_jobs():
            data = ItemListSchema(items=[self.JobModel.parse_job(job) for job in self.scheduler.get_jobs()])
            data.total = len(data.items)
            return BaseApiOut(data=data)

        @self.router.post("/item/{item_id}", response_model=BaseApiOut[List[self.JobModel]], include_in_schema=True)
        async def modify_job(
                item_id: List[str] = Depends(parser_item_id),
                action: Literal['auto', 'remove', 'pause', 'resume'] = None,
                data: self.schema_update = Body(default=None),  # type: ignore
        ):
            jobs = []
            for i in item_id:
                job = self.scheduler.get_job(job_id=i)
                if job:
                    if action is None:
                        job.modify(**data.dict(exclude_unset=True))
                    elif action == 'auto':
                        job.pause() if job.next_run_time else job.resume()
                    elif action == 'pause':
                        job.pause()
                    elif action == 'resume':
                        job.resume()
                    elif action == 'remove':
                        job.remove()
                    jobs.append(self.JobModel.parse_job(job))
            return BaseApiOut(data=jobs)

        return super().register_router()
