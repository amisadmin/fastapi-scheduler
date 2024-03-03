from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from apscheduler.job import Job
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import BaseScheduler
from fastapi import Body, Depends
from fastapi_amis_admin import admin
from fastapi_amis_admin.admin import AdminApp
from fastapi_amis_admin.amis import (
    Action,
    ActionType,
    Dialog,
    Form,
    FormItem,
    InputDatetime,
    Page,
    PageSchema,
    SchemaNode,
    SizeEnum,
    TableColumn,
    TableCRUD,
)
from fastapi_amis_admin.crud.schema import (
    BaseApiOut,
    CrudEnum,
    ItemListSchema,
    Paginator,
)
from fastapi_amis_admin.crud.utils import ItemIdListDepend
from fastapi_amis_admin.models.fields import Field
from fastapi_amis_admin.utils.pydantic import (
    ModelField,
    create_model_by_model,
    model_fields,
)
from fastapi_amis_admin.utils.translation import i18n as _
from pydantic import BaseModel, validator
from starlette.requests import Request
from typing_extensions import Annotated, Literal
import tzlocal


class SchedulerAdmin(admin.PageAdmin):
    page_schema = PageSchema(label=_("APScheduler"), icon="fa fa-clock-o")
    page_path = "/"
    router_prefix = "/jobs"
    scheduler: BaseScheduler = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore()},
        timezone=tzlocal.get_localzone_name(),
    )

    class JobModel(BaseModel):
        id: str = Field(..., title=_("Job ID"))
        name: str = Field(..., title=_("Job Name"))
        next_run_time: Optional[datetime] = Field(
            None,
            title=_("Next Run Time"),
            amis_form_item=InputDatetime(format="YYYY-MM-DDTHH:mm:ss.SSSSSSZ"),
        )
        trigger: Optional[str] = Field(None, title=_("Trigger"))  # BaseTrigger
        func_ref: str = Field(..., title=_("Function"))
        args: List[Any] = Field([], title=_("Tuple Args"), amis_table_column="list")
        kwargs: Dict[str, Any] = Field(
            {},
            title=_("Keyword Args"),
            amis_table_column="json",
            amis_form_item="json-editor",
        )
        executor: str = Field("default", title=_("Executor"))
        max_instances: Optional[int] = Field(None, title=_("Max Instances"))
        misfire_grace_time: Optional[int] = Field(None, title=_("Misfire Grace Time"))
        coalesce: Optional[bool] = Field(None, title=_("Coalesce"))

        @validator("trigger", pre=True)
        def trigger_valid(cls, v):  # sourcery skip: instance-method-first-arg-name
            return str(v)

        @classmethod
        def parse_job(cls, job: Job):
            return job and cls(**{k: getattr(job, k, None) for k in model_fields(cls)})

    @classmethod
    def bind(cls, app: AdminApp, scheduler: BaseScheduler = None) -> BaseScheduler:
        cls.scheduler = scheduler or cls.scheduler
        app.register_admin(cls)
        return cls.scheduler

    def __init__(self, app: "AdminApp"):
        super().__init__(app)
        self.schema_update = create_model_by_model(
            self.JobModel,
            "JobsUpdate",
            include={"name", "next_run_time"},
            set_none=True,
        )
        self.paginator = Paginator(perPageMax=100)

    async def get_page(self, request: Request) -> Page:
        page = await super().get_page(request)
        headerToolbar = [
            "reload",
            "bulkActions",
            {"type": "columns-toggler", "align": "right"},
            {"type": "drag-toggler", "align": "right"},
            {"type": "pagination", "align": "right"},
            {
                "type": "tpl",
                "tpl": _("SHOWING ${items|count} OF ${total} RESULT(S)"),
                "className": "v-middle",
                "align": "right",
            },
        ]
        page.body = TableCRUD(
            api=f"get:{self.router_path}/list",
            autoFillHeight=True,
            headerToolbar=headerToolbar,
            filterTogglable=True,
            filterDefaultVisible=False,
            syncLocation=False,
            keepItemSelectionOnPageChange=True,
            footerToolbar=[
                "statistics",
                "switch-per-page",
                "pagination",
                "load-more",
                "export-csv",
            ],
            columns=await self.get_list_columns(request),
            itemActions=await self.get_actions_on_item(request),
            bulkActions=await self.get_actions_on_bulk(request),
            quickSaveItemApi=f"{self.router_path}/item/$id",
        )
        return page

    async def get_list_columns(self, request: Request) -> List[TableColumn]:
        columns = []
        update_fields = model_fields(self.schema_update)
        for modelfield in model_fields(self.JobModel).values():
            column = self.site.amis_parser.as_table_column(modelfield, quick_edit=modelfield.name in update_fields)
            if column:
                columns.append(column)
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

        api = f"{self.router_path}/item/" + ("${ids|raw}" if bulk else "$id")
        fields = model_fields(self.schema_update).values()
        return Form(
            api=api,
            name=CrudEnum.update,
            body=[await self.get_form_item(request, field, action=CrudEnum.update) for field in fields],
            submitText=None,
            trimValues=True,
        )

    async def get_update_action(self, request: Request, bulk: bool = False) -> Optional[Action]:
        return ActionType.Dialog(
            icon="fa fa-pencil",
            tooltip=_("Update"),
            dialog=Dialog(
                title=_("Update"),
                size=SizeEnum.lg,
                body=await self.get_update_form(request, bulk=bulk),
            ),
        )

    async def get_job_action(
        self,
        request: Request,
        bulk: bool = False,
        action: Literal["auto", "remove", "pause", "resume"] = "remove",
    ) -> Optional[Action]:
        label, icon = {
            "remove": (_("remove"), "fa-times text-danger"),
            "pause": (_("pause"), "fa-pause"),
            "resume": (_("resume"), "fa-play"),
        }[action]
        return (
            ActionType.Ajax(
                icon=f"fa {icon}",
                tooltip=_("Bulk %s") % label,
                confirmText=_("Are you sure you want to batch %s selected tasks?") % label,
                api=f"{self.router_path}/item/" + "${ids|raw}?action=" + action,
            )
            if bulk
            else ActionType.Ajax(
                icon=f"fa {icon}",
                tooltip=label,
                confirmText=_("Are you sure you want to %s the selected task?") % label,
                api=f"{self.router_path}/item/$id?action={action}",
            )
        )

    async def get_form_item(self, request: Request, modelfield: ModelField, action: CrudEnum) -> Union[FormItem, SchemaNode]:
        is_filter = action == CrudEnum.list
        return self.site.amis_parser.as_form_item(modelfield, is_filter=is_filter)

    def register_router(self):
        @self.router.get(
            "/list",
            response_model=BaseApiOut[ItemListSchema[self.JobModel]],
            include_in_schema=True,
        )
        async def get_jobs(paginator: Annotated[self.paginator, Depends()]):  # type: ignore
            jobs = self.scheduler.get_jobs()
            start = (paginator.page - 1) * paginator.perPage
            end = paginator.page * paginator.perPage
            data = ItemListSchema(items=[self.JobModel.parse_job(job) for job in jobs[start:end]])
            data.total = len(jobs) if paginator.show_total else None
            return BaseApiOut(data=data)

        @self.router.post(
            "/item/{item_id}",
            response_model=BaseApiOut[List[self.JobModel]],
            include_in_schema=True,
        )
        async def modify_job(
            item_id: ItemIdListDepend,
            action: Literal["auto", "remove", "pause", "resume"] = None,
            data: Annotated[self.schema_update, Body()] = None,  # type: ignore
        ):
            jobs = []
            for i in item_id:
                job = self.scheduler.get_job(job_id=i)
                if job:
                    if action is None:
                        job.modify(**data.dict(exclude_unset=True))
                    elif action == "auto":
                        job.pause() if job.next_run_time else job.resume()
                    elif action == "pause":
                        job.pause()
                    elif action == "resume":
                        job.resume()
                    elif action == "remove":
                        job.remove()
                    jobs.append(self.JobModel.parse_job(job))
            return BaseApiOut(data=jobs)

        return super().register_router()
