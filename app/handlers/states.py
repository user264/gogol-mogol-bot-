from aiogram.fsm.state import State, StatesGroup


class AddShiftFSM(StatesGroup):
    choose_cook = State()
    choose_date = State()
    choose_hours = State()  # inline hour buttons
    enter_hours = State()   # custom text input
    confirm = State()       # kept for safety


class EditShiftFSM(StatesGroup):
    choose_cook = State()
    choose_date = State()
    choose_hours = State()  # inline hour buttons
    enter_hours = State()   # custom text input
    enter_reason = State()


class AddCookFSM(StatesGroup):
    enter_name = State()
    enter_rate = State()
    enter_telegram = State()


class EditRateFSM(StatesGroup):
    choose_cook = State()
    enter_rate = State()


class SetRevenueFSM(StatesGroup):
    enter_amount = State()


class SetConfigFSM(StatesGroup):
    choose_param = State()
    enter_value = State()


class AddUserFSM(StatesGroup):
    choose_role = State()
    enter_telegram = State()
    enter_rate = State()
    choose_cook = State()


class ChangeRoleFSM(StatesGroup):
    choose_user = State()
    choose_role = State()
    enter_rate = State()
    choose_cook = State()


class DeactivateCookFSM(StatesGroup):
    choose_cook = State()
    confirm_delete = State()


class FeedbackFSM(StatesGroup):
    choose_anon = State()
    enter_text = State()


class MonthlyReportFSM(StatesGroup):
    choose_period = State()
    choose_cook = State()
