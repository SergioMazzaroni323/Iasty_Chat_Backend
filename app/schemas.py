from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    plan: str
    tier: str
    token_limit: int
    is_admin: bool = False
    is_active: bool = True
    email_verified: bool = False

    class Config:
        from_attributes = True


class StatusMessageResponse(BaseModel):
    message: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class VerifyEmailResponse(BaseModel):
    message: str
    access_token: str
    token_type: str = "bearer"


class ResendRegistrationRequest(BaseModel):
    email: EmailStr


class AdminStatsResponse(BaseModel):
    total_users: int
    plus_users: int
    free_users: int
    total_chats: int
    guest_chats: int
    total_messages: int
    total_tokens: int


class AdminUserResponse(BaseModel):
    id: int
    email: str
    username: str
    plan: str
    is_admin: bool
    is_active: bool
    email_verified: bool
    chat_count: int
    token_used: int
    additional_data_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserUpdateRequest(BaseModel):
    plan: str | None = None
    is_admin: bool | None = None


class AdminChatResponse(BaseModel):
    id: int
    name: str
    user_id: int | None
    username: str | None
    message_count: int
    token_used: int
    created_at: datetime
    updated_at: datetime


class UpdateUserRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    current_password: str | None = None
    new_password: str | None = None
    is_active: bool | None = None


class PlanUpdateRequest(BaseModel):
    plan: str


class ChatCreate(BaseModel):
    name: str = "New Chat"
    guest_id: str | None = None


class ChatUpdate(BaseModel):
    name: str | None = None
    folder_id: int | None = None


class ChatFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)


class ChatFolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=500)


class ChatFolderResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatResponse(BaseModel):
    id: int
    name: str
    folder_id: int | None = None
    token_used: int
    token_limit: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    token_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChatDetailResponse(ChatResponse):
    messages: list[MessageResponse]


class SendMessageRequest(BaseModel):
    content: str = ""
    model: str
    web_search: bool = False
    guest_id: str | None = None
    edit_message_id: int | None = None
    document_text: str | None = None
    document_filename: str | None = None
    additional_data_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_content_or_document(self):
        has_content = bool(self.content.strip())
        has_document = bool(self.document_text and self.document_text.strip())
        if not has_content and not has_document:
            raise ValueError("Message content or PDF attachment is required")
        return self


class ParsePdfResponse(BaseModel):
    filename: str
    text: str
    page_count: int
    char_count: int
    token_estimate: int


class AdditionalDataCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    content: str = ""
    guest_id: str | None = None


class AdditionalDataUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    content: str | None = None


class AdditionalDataAppendRequest(BaseModel):
    content: str = Field(min_length=1)


class AdditionalDataResponse(BaseModel):
    id: int
    name: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ParseFilesResponse(BaseModel):
    text: str
    filenames: list[str]


class ModelInfo(BaseModel):
    id: str
    name: str
    available: bool = True


class ConfigResponse(BaseModel):
    models: list[ModelInfo]
    basic_model: str
    tiers: dict
    current_tier: str
    allowed_models: list[str]
    web_search_available: bool = True
