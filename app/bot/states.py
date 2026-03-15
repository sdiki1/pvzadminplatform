from aiogram.fsm.state import State, StatesGroup


class OpenShiftState(StatesGroup):
    waiting_point = State()
    waiting_location = State()


class CloseShiftState(StatesGroup):
    waiting_location = State()


class ExpenseState(StatesGroup):
    waiting_point = State()
    waiting_category = State()
    waiting_amount = State()
    waiting_description = State()


class PayrollState(StatesGroup):
    waiting_day = State()
    waiting_critical_code = State()
