import re
from collections.abc import Iterator
from datetime import timedelta
from functools import cached_property

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger
from module.ocr.ocr import DigitCounter, Duration, Ocr
from module.ui.draggable_list import DraggableList
from tasks.assignment.assets.assets_assignment_ui import *
from tasks.assignment.keywords import *
from tasks.base.ui import UI


class AssignmentOcr(Ocr):
    # EN has names in multiple rows
    merge_thres_y = 20
    merge_thres_x = 20

    OCR_REPLACE = {
        'cn': [
            (KEYWORDS_ASSIGNMENT_ENTRY.Winter_Soldiers.name, '[黑]冬的战士们'),
            (KEYWORDS_ASSIGNMENT_ENTRY.Born_to_Obey.name, '[牛]而服从'),
            (KEYWORDS_ASSIGNMENT_ENTRY.Root_Out_the_Turpitude.name,
             '根除恶[擎薯尊掌鞋]?'),
            (KEYWORDS_ASSIGNMENT_ENTRY.Akashic_Records.name, '阿[未][夏复]记录'),
            (KEYWORDS_ASSIGNMENT_ENTRY.Legend_of_the_Puppet_Master.name, '^师传说'),
            (KEYWORDS_ASSIGNMENT_ENTRY.The_Wages_of_Humanity.name, '[赠]养人类'),
            (KEYWORDS_ASSIGNMENT_EVENT_GROUP.Space_Station_Task_Force.name,
             '[新0]空间站特派[新]'),
        ],
        'en': [
            (KEYWORDS_ASSIGNMENT_EVENT_ENTRY.Food_Improvement_Plan.name,
             'Food\s*[I]{0}mprovement Plan'),
            (KEYWORDS_ASSIGNMENT_EVENT_GROUP.Space_Station_Task_Force.name,
             '^(S[np]ace Station Ta[^sk]{0,3})?[F-]orce')
        ]
    }

    @cached_property
    def ocr_regex(self) -> re.Pattern | None:
        rules = AssignmentOcr.OCR_REPLACE.get(self.lang)
        if rules is None:
            return None
        return re.compile('|'.join('(?P<%s>%s)' % pair for pair in rules))

    def filter_detected(self, result) -> bool:
        # Drop duration rows
        res = Duration.timedelta_regex(self.lang).search(result.ocr_text)
        if res.group('hours') or res.group('seconds'):
            return False
        # Locked event assignments
        locked_pattern = {
            'cn': '解锁$',
            'en': 'Locked$',
        }[self.lang]
        res = re.search(locked_pattern, result.ocr_text)
        return not res

    def after_process(self, result: str):
        result = super().after_process(result)

        if self.ocr_regex is None:
            return result
        matched = self.ocr_regex.fullmatch(result)
        if matched is None:
            return result
        keyword_lang = self.lang
        for keyword_class in (
            KEYWORDS_ASSIGNMENT_ENTRY, KEYWORDS_ASSIGNMENT_EVENT_ENTRY,
            KEYWORDS_ASSIGNMENT_GROUP, KEYWORDS_ASSIGNMENT_EVENT_GROUP,
        ):
            try:
                matched = getattr(keyword_class, matched.lastgroup)
                break
            except AttributeError:
                continue
        else:
            raise ScriptError(f'No keyword found for {matched.lastgroup}')
        matched = getattr(matched, keyword_lang)
        logger.attr(name=f'{self.name} after_process',
                    text=f'{result} -> {matched}')
        return matched


ASSIGNMENT_GROUP_LIST = DraggableList(
    'AssignmentGroupList',
    keyword_class=[AssignmentGroup, AssignmentEventGroup],
    ocr_class=AssignmentOcr,
    search_button=OCR_ASSIGNMENT_GROUP_LIST,
    check_row_order=False,
    active_color=(240, 240, 240),
    drag_direction='right'
)
ASSIGNMENT_ENTRY_LIST = DraggableList(
    'AssignmentEntryList',
    keyword_class=[AssignmentEntry, AssignmentEventEntry],
    ocr_class=AssignmentOcr,
    search_button=OCR_ASSIGNMENT_ENTRY_LIST,
    check_row_order=False,
    active_color=(40, 40, 40)
)


class AssignmentUI(UI):
    def goto_group(self, group: AssignmentGroup):
        """
        Args:
            group (AssignmentGroup):

        Examples:
            self = AssignmentUI('src')
            self.device.screenshot()
            self.goto_group(KEYWORDS_ASSIGNMENT_GROUP.Character_Materials)
        """
        selected = ASSIGNMENT_GROUP_LIST.get_selected_row(self)
        if selected and selected.matched_keyword == group:
            return
        logger.hr('Assignment group goto', level=3)
        self._wait_until_group_loaded()
        if ASSIGNMENT_GROUP_LIST.select_row(group, self):
            self._wait_until_entry_loaded()

    def goto_entry(self, entry: AssignmentEntry):
        """
        Args:
            entry (AssignmentEntry):

        Examples:
            self = AssignmentUI('src')
            self.device.screenshot()
            self.goto_entry(KEYWORDS_ASSIGNMENT_ENTRY.Nameless_Land_Nameless_People)
        """
        if entry.group is None:
            err_msg = f'{entry} is not in any group, please inform developers if possible'
            logger.warning(err_msg)
            for group in self._iter_groups():
                self.goto_group(group)
                if ASSIGNMENT_ENTRY_LIST.select_row(entry, self):
                    return
            raise ScriptError(err_msg)
        else:
            self.goto_group(entry.group)
            ASSIGNMENT_ENTRY_LIST.select_row(entry, self)

    def _wait_until_group_loaded(self):
        skip_first_screenshot = True
        timeout = Timer(2, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Wait group loaded timeout')
                break
            if self.image_color_count(OCR_ASSIGNMENT_GROUP_LIST, (40, 40, 40), count=20000) and \
                    self.image_color_count(OCR_ASSIGNMENT_GROUP_LIST, (240, 240, 240), count=7000):
                logger.info('Group loaded')
                break

    def _wait_until_entry_loaded(self):
        skip_first_screenshot = True
        timeout = Timer(2, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                logger.warning('Wait entry loaded timeout')
                break
            # Maybe not reliable
            if self.image_color_count(ENTRY_LOADED, (35, 35, 35)):
                logger.info('Entry loaded')
                break

    @property
    def _limit_status(self) -> tuple[int, int, int]:
        self.device.screenshot()
        current, remain, total = DigitCounter(
            OCR_ASSIGNMENT_LIMIT).ocr_single_line(self.device.image)
        if total and current <= total:
            logger.attr('Assignment', f'{current}/{total}')
            self.config.stored.Assignment.set(current, total)
        else:
            logger.warning(f'Invalid assignment limit: {current}/{total}')
            self.config.stored.Assignment.set(0, 0)
        return current, remain, total

    def _get_assignment_time(self) -> timedelta:
        return Duration(OCR_ASSIGNMENT_TIME).ocr_single_line(self.device.image)

    def _iter_groups(self) -> Iterator[AssignmentGroup]:
        self._wait_until_group_loaded()
        ASSIGNMENT_GROUP_LIST.insight_row(
            KEYWORDS_ASSIGNMENT_GROUP.Character_Materials, self)
        for button in ASSIGNMENT_GROUP_LIST.cur_buttons:
            yield button.matched_keyword

    def _iter_entries(self) -> Iterator[AssignmentEntry]:
        """
        Iterate entries from top to bottom
        """
        ASSIGNMENT_ENTRY_LIST.load_rows(main=self)
        # Freeze ocr results here
        yield from [
            button.matched_keyword
            for button in ASSIGNMENT_ENTRY_LIST.cur_buttons
        ]
