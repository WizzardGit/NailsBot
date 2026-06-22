from aiogram.fsm.state import State, StatesGroup


class LeadStates(StatesGroup):
    waiting_custom_source = State()


class BookingStates(StatesGroup):
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    waiting_contact = State()
    confirming = State()


class ReviewStates(StatesGroup):
    waiting_text = State()

