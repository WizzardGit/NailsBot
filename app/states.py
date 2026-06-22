from aiogram.fsm.state import State, StatesGroup


class LeadStates(StatesGroup):
    waiting_custom_source = State()


class BookingStates(StatesGroup):
    choosing_services = State()
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    waiting_contact = State()
    confirming = State()


class ReviewStates(StatesGroup):
    waiting_text = State()


class AdminServiceStates(StatesGroup):
    waiting_title = State()
    waiting_price = State()
    waiting_duration = State()
    waiting_description = State()
    confirming_add = State()
    editing_title = State()
    editing_price = State()
    editing_duration = State()
    editing_description = State()


class AdminBookingStates(StatesGroup):
    choosing_reschedule_date = State()
    choosing_reschedule_time = State()
    waiting_cancel_reason = State()


class AdminRoleStates(StatesGroup):
    waiting_user_id = State()
    waiting_role = State()


class AdminBlockedStates(StatesGroup):
    choosing_block_date = State()
    waiting_block_day = State()
    waiting_block_slot_date = State()
    waiting_block_start_time = State()
    waiting_block_end_time = State()
    waiting_block_reason = State()


class ClientSearchStates(StatesGroup):
    waiting_query = State()
