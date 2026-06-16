from pydantic import BaseModel, Field


class Course(BaseModel):
    """Course model"""

    courseId: str = Field(..., description="Course ID")
    clazzId: str = Field(..., description="Class ID")
    cpi: str = Field(..., description="Course participation ID")
    name: str | None = Field(None, description="Course name")


class Point(BaseModel):
    """Course point/chapter model"""

    id: str = Field(..., description="Point ID")
    name: str | None = Field(None, description="Point name")


class Job(BaseModel):
    """Job/task model"""

    jobid: str = Field(..., description="Job ID")
    objectid: str = Field(..., description="Object ID")
    otherinfo: str = Field(..., description="Other information")
    name: str | None = Field(None, description="Job name")
    playTime: int | None = Field(0, description="Play time in milliseconds")
    rt: str | None = Field(None, description="Rate parameter")
    videoFaceCaptureEnc: str | None = Field(None, description="Video face capture encryption")
    attDuration: str | None = Field(None, description="Attention duration")
    attDurationEnc: str | None = Field(None, description="Attention duration encryption")
    enc: str | None = Field(None, description="Encryption parameter")


class JobInfo(BaseModel):
    """Job information model"""

    knowledgeid: str = Field(..., description="Knowledge ID")
    ktoken: str = Field(..., description="Knowledge token")
    cpi: str = Field(..., description="Course participation ID")
    notOpen: bool = Field(False, description="Whether the chapter is not open")
