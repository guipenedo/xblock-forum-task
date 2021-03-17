import json

import pkg_resources
import six
from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.student.models import user_by_anonymous_id, anonymous_id_for_user
from django.core.exceptions import PermissionDenied
from openedx.core.djangoapps.course_groups.cohorts import get_cohort, get_course_cohorts, get_random_cohort, \
    is_course_cohorted
from submissions import api as submissions_api
from web_fragments.fragment import Fragment
from webob.response import Response
from xblock.core import XBlock
from xblock.fields import Scope, String
from xblock.scorable import ScorableXBlockMixin, Score
from xblockutils.resources import ResourceLoader
from xblockutils.studio_editable import StudioEditableXBlockMixin

ITEM_TYPE = "forum_task"
loader = ResourceLoader(__name__)


def resource_string(path):
    """Handy helper for getting resources from our kit."""
    data = pkg_resources.resource_string(__name__, path)
    return data.decode("utf8")


def format_name(name):
    names = name.split()
    if len(names) > 0:
        name = names[0]
    if len(names) > 1:
        name += " " + names[-1]
    return name


class ForumTaskXBlock(XBlock, ScorableXBlockMixin, StudioEditableXBlockMixin):
    display_name = String(display_name="display_name",
                          default="Tarefa fórum",
                          scope=Scope.settings,
                          help="Nome do componente na plataforma")

    prompt = String(display_name="prompt",
                    default="Coloca aqui o link para a tua tarefa no fórum para que um instrutor te atribua 1 ponto (poderá demorar algum tempo).",
                    scope=Scope.settings,
                    help="Texto \"prompt\" que aparece associado a esta tarefa.")

    waiting_msg = String(display_name="waiting_msg",
                         default="Um instrutor irá verificar a tua submissão brevemente.",
                         scope=Scope.settings,
                         help="Texto após submissão de link, quando ainda à espera de resposta.")

    completed_msg = String(display_name="waiting_msg",
                           default="Parabéns! Conseguiste realizar esta tarefa!",
                           scope=Scope.settings,
                           help="Texto após submissão já avaliada pelo instrutor.")

    cohort = String(display_name="cohort",
                    default="",
                    scope=Scope.preferences,
                    help="Turma selecionada")

    editable_fields = ('display_name', 'prompt', 'waiting_msg', 'completed_msg')
    icon_class = 'problem'
    block_type = 'problem'
    has_score = True
    has_author_view = True

    # ----------- Views -----------
    def author_view(self, _context):
        return Fragment(
            "<p>Utilizar em modo View Live ou Preview.</p>")

    def get_prompt(self):
        if not self.has_submitted_answer():
            return self.prompt
        if self.get_score() and self.get_score().raw_earned == 1.0:
            return self.completed_msg
        return self.waiting_msg

    def get_cohorts(self):
        cohorts = [""] + [group.name for group in get_course_cohorts(course_id=self.course_id)]
        random_cohort = get_random_cohort(self.course_id)
        if random_cohort and random_cohort.name in cohorts:
            cohorts.remove(random_cohort.name)
        return cohorts

    def get_user_submission(self, user_id):
        subs = submissions_api.get_submissions(self.get_student_item_dict(user_id), 1)
        if len(subs) > 0:
            return subs[0]

    def add_waiting_submission(self, link):
        submissions_api.create_submission(self.get_student_item_dict(self.user_id), {
            'link': link,
            'validated_by': None
        }, attempt_number=1)

    def set_as_validated(self, user_id, system=False):
        sub = self.get_user_submission(user_id)
        new_sub = submissions_api.create_submission(self.get_student_item_dict(user_id), {
            'link': sub['answer']['link'] if sub else None,
            'validated_by': self.username if not system else "System"
        }, attempt_number=1, submitted_at=sub['submitted_at'] if sub else None)
        submissions_api.set_score(new_sub["uuid"], 1, 1)

    def is_validated(self, user_id):
        sub = self.get_user_submission(user_id)
        if not sub:
            return False
        return sub['answer']['validated_by'] is not None

    def set_as_invalidated(self, user_id):
        sub = self.get_user_submission(user_id)
        if sub:
            new_sub = submissions_api.create_submission(self.get_student_item_dict(user_id), {
                'link': sub['answer']['link'],
                'validated_by': None
            }, attempt_number=1, submitted_at=sub['submitted_at'])
            submissions_api.set_score(new_sub["uuid"], 0, 1)

    def student_view(self, _context):
        """
            The view students see
        :param _context:
        :return:
        """
        data = {
            'prompt': self.get_prompt(),
            'xblock_id': self._get_xblock_loc(),
            'is_course_staff': False,
            'show_form': not self.has_submitted_answer()
        }
        if self.show_staff_grading_interface():
            data['is_course_staff'] = True

        html = loader.render_django_template('templates/forumtask.html', data)
        frag = Fragment(html)

        frag.add_javascript(resource_string("static/js/forum_task_script.js"))
        frag.add_css(resource_string("static/css/forum_task.css"))
        frag.initialize_js('ForumTaskXBlock', data)
        return frag

    def is_in_cohort(self, user):
        if not is_course_cohorted(self.course_id):
            return True
        cohort = get_cohort(user, self.course_id, assign=False, use_cached=True)
        return cohort and (not self.cohort or cohort.name == self.cohort)

    @XBlock.handler
    def load_submissions(self, request, suffix=''):
        if not self.show_staff_grading_interface():
            raise PermissionDenied
        enrollments = CourseEnrollment.objects.filter(course_id=self.course_id)

        all_submissions = {
            str(sub['student_id']): {
                'submission_id': sub['uuid'],
                'user_id': sub['student_id'],
                'timestamp': (sub['submitted_at'] or sub['created_at']).strftime("%d/%m/%Y %H:%M:%S"),
                'link': sub['answer']['link'],
                'validated_by': sub['answer']['validated_by']
            } for sub in submissions_api.get_all_submissions(
                self.block_course_id,
                self.block_id,
                ITEM_TYPE
            )}

        # names only for this cohort
        names = {}
        no_submission = []
        cohort_submissions = []

        for enr in enrollments:
            if self.is_in_cohort(enr.user):
                user_id = anonymous_id_for_user(enr.user, self.course_id)

                if user_id in all_submissions:
                    cohort_submissions.append(all_submissions[user_id])
                else:
                    no_submission.append(user_id)

                names[user_id] = enr.user.username
                if enr.user.profile.name:
                    names[user_id] = self.format_name(enr.user.profile.name)

        return Response(json.dumps({
            'submissions': cohort_submissions,
            'not_submitted': no_submission,
            'names': names,
            'cohorts': self.get_cohorts(),
            'is_course_cohorted': is_course_cohorted(self.course_id),
            'cohort': self.cohort
        }))

    @XBlock.json_handler
    def submit_link(self, data, _suffix):
        """
            Triggered when the user presses the submit button.
        :param data:
        :param _suffix:
        :return:
        """
        if not self.has_submitted_answer() and "link" in data and data["link"]:
            self.add_waiting_submission(data["link"])
            return {
                'result': 'success'
            }
        return {
            'result': 'error',
            'message': 'Apenas uma submissão por aluno.'
        }

    @XBlock.json_handler
    def validate_submission(self, data, _suffix):
        """
            Triggered when the user presses the submit button.
        :param data:
        :param _suffix:
        :return:
        """
        if self.show_staff_grading_interface() and "user_id" in data and data["user_id"]:
            user_id = data["user_id"]
            if self.is_validated(user_id):
                self.set_as_invalidated(user_id)
            else:
                self.set_as_validated(user_id)
            return {
                'result': 'success'
            }
        return {
            'result': 'error',
            'message': 'Apenas staff pode validar submissões/falta user_id.'
        }

    @XBlock.json_handler
    def change_cohort(self, data, _suffix):
        self.cohort = data["cohort"]
        return {
            'result': 'success'
        }

    @property
    def user_id(self):
        return self.xmodule_runtime.anonymous_student_id

    @property
    def username(self):
        return user_by_anonymous_id(self.xmodule_runtime.anonymous_student_id).username

    def _get_xblock_loc(self):
        """Returns trailing number portion of self.location"""
        return str(self.location).split('@')[-1]

    def show_staff_grading_interface(self):
        """
        Return if current user is staff and not in studio.
        """
        in_studio_preview = self.scope_ids.user_id is None
        return getattr(self.xmodule_runtime, 'user_is_staff', False) and not in_studio_preview

    def has_submitted_answer(self):
        return self.get_user_submission(self.user_id) is not None

    def max_score(self):
        return 1

    def get_score(self):
        if not self.is_validated(self.user_id):
            return None
        return Score(raw_earned=1.0, raw_possible=1.0)

    def set_score(self, score):
        if score['raw_earned'] == 0.0:
            self.set_as_invalidated(self.user_id)
        else:
            self.set_as_validated(self.user_id, True)

    def calculate_score(self):
        return self.get_score()

    @property
    def block_course_id(self):
        return six.text_type(self.course_id)

    @property
    def block_id(self):
        return six.text_type(self.scope_ids.usage_id)

    def get_student_item_dict(self, student_id=None):
        """
        Returns dict required by the submissions app for creating and
        retrieving submissions for a particular student.
        """
        if student_id is None:
            student_id = self.xmodule_runtime.anonymous_student_id
        return {
            "student_id": student_id,
            "course_id": self.block_course_id,
            "item_id": self.block_id,
            "item_type": ITEM_TYPE,
        }
