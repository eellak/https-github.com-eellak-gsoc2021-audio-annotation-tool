# Functions used for views
import random
from zipfile import ZipFile
from rarfile import RarFile
from itertools import chain
import os
import json
from tensorflow import keras
import torch
import numpy as np
import requests
import docker
import yaml

from django.core.files import File
from django.db.models import Q
from django.template.defaulttags import register

from .models import Project, Label
from users.models import User
from tasks.models import (
    Task,
    Annotation,
    Comment,
    Status,
    Review_status,
    Annotation_status,
)

# Global variables
ACCEPTED_FORMATS = ['.wav', '.mp3', '.mp4', ]
CONTAINER_URL = '127.0.0.1'
CONTAINER_PORT = '5000'

# Functions

def get_projects_of_user(user):

    """
    Get projects in which user is manager, annotator or reviewer.
    """

    return Project.objects.prefetch_related('labels').prefetch_related('annotators').prefetch_related('reviewers').prefetch_related('managers').filter(Q(reviewers__in=[user]) | Q(annotators__in=[user]) | Q(managers__in=[user])).distinct()


def get_user(username):

    """
    Get user by username.
    """

    try:
        user = User.objects.get(username=username)
        return user
    except User.DoesNotExist:
        return None


def get_project(pk):

    """
    Get projects by id.
    """

    try:
        project = Project.objects.prefetch_related('annotators').prefetch_related('reviewers').prefetch_related('managers').get(pk=pk)
        return project
    except Project.DoesNotExist:
        return None


def get_task(pk):

    """
    Get task by id.
    """

    try:
        task = Task.objects.get(pk=pk)
        return task
    except Task.DoesNotExist:
        return None


def get_annotation(task, project, user):

    """
    Get annotation by task, project and user.
    """

    try:
        annotation = Annotation.objects.get(task=task, project=project, user=user)
        return annotation
    except Annotation.DoesNotExist:
        return None


def get_annotation_by_id(pk):

    """
    Get annotation by id (pk).
    """

    try:
        annotation = Annotation.objects.get(pk=pk)
        return annotation
    except Annotation.DoesNotExist:
        return None


def get_annotation_result(task, project, user):

    """
    Get annotation updated_at and result by task, project and user.
    """

    try:
        annotation = Annotation.objects.get(task=task, project=project, user=user)
        return annotation.result
    except Annotation.DoesNotExist:
        return []


def get_annotation_review(user, annotation):

    """
    Get review of an annotation.
    """

    try:
        review = Comment.objects.get(reviewed_by=user, annotation=annotation)
        return review
    except Comment.DoesNotExist:
        return None


def is_user_involved(user, project):

    """
    Check if user involved at a project as a manager, annotator or reviewer.
    """

    return (user in project.annotators.all()) or (user in project.reviewers.all()) or (user in project.managers.all())


def if_annotation_reviewed(annotation):

    """
    Get information for an annotation's review.
    """

    try:
        review = Comment.objects.get(annotation=annotation)
        return review.reviewed_by, review.comment, review.created_at, review.updated_at
    except Comment.DoesNotExist:
        return None, None, None, None


def get_label(name):

    """
    Get label by name.
    """

    try:
        label = Label.objects.get(pk=name)
        return label
    except Label.DoesNotExist:
        return None


def get_label_by_color(color):

    """
    Get label by color.
    """

    try:
        label = Label.objects.get(color=color)
        return label
    except Label.DoesNotExist:
        return None


def random_color():

    """
    Get random color.
    """

    random_number = random.randint(0, 16777215)
    hex_number = str(hex(random_number))
    return '#' + hex_number[2:]


# Functions for index page


def get_num_of_tasks(projects):

    """
    Return a dictionary id: number of tasks for each project.
    """

    context = {}

    for project in projects:
        context[project.id] = Task.objects.filter(project=project).count()
    return context


def project_annotations_count(projects):

    """
    Return a dictionary id: number of annotations for each project.
    """

    context = {}
    for project in projects:
        context[project.id] = Annotation.objects.filter(project=project).count()
    return context


def get_project_tasks(project):

    """
    Get all tasks of a project and return them.
    """

    return Task.objects.filter(project=project)


def add_labels_to_project(project, labels):

    """
    Create labels that don't exist and add all of them to the project labels.
    """

    new_labels = labels.split(',')
    labels_of_project = project.labels.all()
    for new in new_labels:
        name = new.strip()
        label = get_label(name)
        if not label:
            color = random_color()
            # Make sure the color does not already exist
            while get_label_by_color(color):
                color = random_color()
            if name != "":
                label = Label.objects.create(name=name, color=color)
        if label and label not in labels_of_project:
            project.labels.add(label)


def delete_old_labels(project):

    """
    Delete all labels of a project.
    """

    for label in project.labels.all():
        project.labels.remove(label)


def users_to_string(users):

    """
    Return users emails with <br> element for using them in tooltip's title.
    User will hover over the text and see all emails.
    """

    to_return_string = ""
    for user in users:
        to_return_string += user.email + "<br/>"
    return to_return_string[:-5]


# Functions for project page


def str_to_bool(string):

    """
    Return boolean of string. If it returns None then the string is not boolean (true or false).
    """

    string = string.lower()
    if string == "true":
        return True
    elif string == "false":
        return False
    return None


def filter_tasks(user, project, labeled, reviewed):

    """
    Return filtered tasks (labeled or unlabeled, reviewed or unreviewed).
    """

    bool_labeled = str_to_bool(labeled)
    bool_reviewed = str_to_bool(reviewed)
    tasks = get_project_tasks(project)

    # Set status and review_status to correct values
    if bool_labeled is not None:
        if bool_labeled:
            status = Status.labeled
        else:
            status = Status.unlabeled

    if bool_reviewed is not None:
        if bool_reviewed:
            review_status = Review_status.reviewed
        else:
            review_status = Review_status.unreviewed

    # If no filters applied
    if bool_labeled is None and bool_reviewed is None:
        pass

    # If both filters applied
    if bool_labeled is not None and bool_reviewed is not None:
        tasks = tasks.filter(status=status, review_status=review_status)

    # If status filter is applied
    if bool_labeled is not None:
        tasks = tasks.filter(status=status)

    # If review filter is applied
    if bool_reviewed is not None:
        tasks = tasks.filter(review_status=review_status)

    # If users_can_see_other_queues is false return only assigned tasks
    # If user is a reviewer he/she must see all tasks in order to review them
    # Manager must see all tasks
    if not project.users_can_see_other_queues:

        assigned_tasks = tasks.filter(Q(assigned_to__in=[user]) | Q(assigned_to=None))
        # If user manager show all tasks
        if user in project.managers.all():
            all_other_tasks = tasks.exclude(pk__in=assigned_tasks.values_list('id', flat=True))
            return list(chain(assigned_tasks, all_other_tasks)), assigned_tasks.count()
        else:
            if user not in project.reviewers.all():
                # If only annotator return assigned tasks
                return assigned_tasks, assigned_tasks.count()
            else:
                # Return all tasks but annotate only assigned ones
                # Concat result so first task shown are the assigned ones
                all_other_tasks = tasks.exclude(pk__in=assigned_tasks.values_list('id', flat=True))
                return list(chain(assigned_tasks, all_other_tasks)), assigned_tasks.count()
    return tasks, 0


def filter_list_annotations(annotations, approved_filter, rejected_filter, unreviewed_filter):

    """
    Filter annotations for list annotations page.
    """

    bool_approved_filter = str_to_bool(approved_filter)
    bool_rejected_filter = str_to_bool(rejected_filter)
    bool_unreviewed_filter = str_to_bool(unreviewed_filter)
    filters_true = 0
    if bool_approved_filter:
        filters_true += 1

    if bool_rejected_filter:
        filters_true += 1

    if bool_unreviewed_filter:
        filters_true += 1

    # Return all annotations
    if not (bool_approved_filter and bool_rejected_filter and bool_unreviewed_filter) and not filters_true == 3:
        if filters_true == 1:
            # Only one filter checked
            if bool_approved_filter:
                annotations = annotations.filter(review_status=Annotation_status.approved)

            if bool_rejected_filter:
                annotations = annotations.filter(review_status=Annotation_status.rejected)

            if bool_unreviewed_filter:
                annotations = annotations.filter(review_status=Annotation_status.no_review)
        else:
            # Two filters checked
            if bool_approved_filter:
                if bool_rejected_filter:
                    annotations = annotations.filter(Q(review_status=Annotation_status.approved) | Q(review_status=Annotation_status.rejected))
                else:
                    annotations = annotations.filter(Q(review_status=Annotation_status.approved) | Q(review_status=Annotation_status.no_review))
            else:
                annotations = annotations.filter(Q(review_status=Annotation_status.rejected) | Q(review_status=Annotation_status.no_review))

    return annotations


def fix_tasks_after_edit(users_can_see_other_queues_old, users_can_see_other_queues_new, project, user):

    """
    Fix taksks after modyfing a project.
    """

    tasks = Task.objects.filter(project=project)
    if users_can_see_other_queues_new == users_can_see_other_queues_old:
        pass

        """
        When an annotor is removed, his/her assigned tasks remain unasigned until the manager
        assigns them again to another annotator. Future work.
        """

    else:
        # If values different
        if users_can_see_other_queues_new:
            # Just set assigned_to for all tasks to None
            for task in tasks:
                task.assigned_to.clear()
        else:
            # Assign tasks randomly to all annotators if annotator exists
            if project.annotators.exists():
                project_annotators_count = project.annotators.count()
                users_already_assigned_id = []
                for task in tasks:
                    # We are sure that assigned_to will be none as we came from public queues
                    assert task.assigned_to.exists() is False

                    # Do this process if there are more than one annotators
                    if project_annotators_count > 1:
                        # Exclude those who are already addigned a task
                        annotators = project.annotators.exclude(id__in=users_already_assigned_id)

                        # Choose one
                        random_annotator = random.choice(list(annotators))
                        task.assigned_to.add(random_annotator)

                        # Add id to list
                        users_already_assigned_id.append(random_annotator.id)

                        # If length of users_already_assigned_id == project.anotators, make it empty (start over)
                        if len(users_already_assigned_id) == project_annotators_count:
                            users_already_assigned_id = []
                    else:
                        # Just assign task to only one
                        task.assigned_to.add(project.annotators.all()[0])


def get_project_url(pk):

    """
    Return project's page url.
    """

    return "/projects/" + str(pk) + "/tasks"


def task_annotations_count(tasks):

    """
    Return dictionary dict[id] = number of annotations for task, for all tasks.
    """

    context = {}
    for task in tasks:
        context[task.id] = Annotation.objects.filter(task=task).count()
    return context


def users_annotated_task(tasks):

    """
    Return two dictionaries dict[task.id] = [user1, userxx, ...] with all users annotated this task and counts.
    """

    task_annotators = {}
    task_annotations_count = {}
    for task in tasks:
        query = Annotation.objects.filter(task=task)
        query_list = query.all()
        annotations_count = query.count()

        if annotations_count == 0:
            task_annotators[task.id] = ""
        elif annotations_count == 1:
            annotation = query_list[0]
            task_annotators[task.id] = annotation.user.email
        else:
            # Create annotators for tooltop title
            annotators = [annotation.user for annotation in query_list]
            task_annotators[task.id] = users_to_string(annotators)
        task_annotations_count[task.id] = annotations_count
    return task_annotators, task_annotations_count


def add_tasks_from_compressed_file(compressed_file, project, file_extension):

    """
    Unzip uploaded file and add contained files to the project.
    """
    
    temp_rar_compoments_folder = '/label_buddy/media/rarcomps'

    if file_extension == ".zip":
        archive = ZipFile(compressed_file, 'r')
    else:
        archive = RarFile(compressed_file, 'r')

    files_names = archive.namelist()
    skipped_files = 0

    """
    Create array to keep users already asigned a task so the tasks are assigned with uniform distribution,
    if users_can_see_other_queues is false.
    """

    project_annotators_count = project.annotators.count()
    users_already_assigned_id = []
    for filename in files_names:

        new_file = archive.open(filename, 'r')
            
        # For every file that has an extension in [.wav, .mp3, .mp4] create a task
        if filename[-4:] in ACCEPTED_FORMATS:
            # Create task
            new_task = Task.objects.create(project=project, original_file_name=filename)
            new_task.file.save(filename, File(new_file))
            new_task.audiowaveform = get_audiowaveform_data(new_task.file.url)
            new_task.save()

            # Assign task
            if not project.users_can_see_other_queues and project.annotators.exists():

                # Do this process if there are more than one annotators
                if project_annotators_count > 1:
                    # Exclude those who are already addigned a task
                    annotators = project.annotators.exclude(id__in=users_already_assigned_id)

                    # Choose one
                    random_annotator = random.choice(list(annotators))
                    new_task.assigned_to.add(random_annotator)

                    # Add id to list
                    users_already_assigned_id.append(random_annotator.id)

                    # If length of users_already_assigned_id == project.anotators, make it empty (start over)
                    if len(users_already_assigned_id) == project_annotators_count:
                        users_already_assigned_id = []
                else:
                    # Just assign task to only one
                    new_task.assigned_to.add(project.annotators.all()[0])
        else:
            skipped_files += 1

    return skipped_files


# Functions for annotation page


def next_unlabeled_task_id(current_task_id, project):

    """
    Return next unlabeled task for the annotator to annotate.
    """

    ordered_tasks = Task.objects.filter(project=project).order_by("-id")
    min_id = ordered_tasks.reverse()[0].id
    max_id = ordered_tasks[0].id

    for task_id in range(min_id, max_id + 1):
        task = get_task(task_id)
        if task and task.file and task_id != current_task_id and task.status == Status.unlabeled:
            return task_id
    return -1


def project_statistics(project, user):

    """
    Project statistics for the annotator to see. Future work.
    """

    # If public tasks
    if project.users_can_see_other_queues:
        all_tasks = Task.objects.filter(project=project)
        all_tasks_count = all_tasks.count()
        annotated_tasks = all_tasks.filter(status=Status.labeled).count()
        not_annotated_tasks = all_tasks_count - annotated_tasks
        return all_tasks_count, annotated_tasks, not_annotated_tasks


# GSoC22 
def get_audiowaveform_data(audio_file):

    """
    Return audio waveform data for the task.
    """

    json_name_without_extension = audio_file.split(".")[0]
    json_name = "media/data/" + json_name_without_extension.split("audio/")[1]

    os.system(f'audiowaveform -i {audio_file[1:]} -o {json_name}.json --pixels-per-second 20 --bits 8')

    with open(json_name + ".json", "r") as f:
        json_data = json.load(f)
    
    f.close()
    os.remove(json_name + ".json")

    return json_data["data"]



@register.filter
def get_item(dictionary, key):

    """
    Custom filter to access dictionary in templates in the following manner: dict[key]
    """

    return dictionary.get(key)


@register.simple_tag
def get_table_id(current_page, objects_per_page, loop_counter):

    """
    Calculate correct id for table in project page. This function is used only for pagination purposes.
    """

    return ((current_page - 1) * objects_per_page) + loop_counter


def get_ml_audio_prediction(audio_file_path, model_title, model_weight_file, container_url): 

    '''
    Predict audio tags using the machine learning model that has been chosen.
    '''

    #docker
    preds = send_audio_to_container_for_preds('.' + audio_file_path, str(model_title), container_url)
    preds_json = json.loads(json.dumps(preds))

    return preds_json


def check_if_model_file_is_valid(model_file):

    '''
    Function that checks the validity of a model file passing in the Tensorflow and 
    Keras APIs.
    '''
    
    # Keras/Tensorflow 
    try:
        print("Trying to load model on Keras...")
        keras.models.load_model(str(model_file))
        print("Model loaded successfully on Keras.")
        return True
    except Exception as e:
        print("Model could not be loaded on Keras. Trying to load model on Tensorflow...")
        print(e)
    
    # Tensorflow
    try:
        print("Trying to load model on Tensorflow...")
        model = torch.load(str(model_file))
        model.eval()
        print("Model loaded successfully on Tensorflow.")
        return True
    except Exception as e:
        print("Loading on Tensorflow failed.")
        print(e)

    return False


def get_docker_image_from_yaml(yaml_file):
    
        '''
        Get the docker image from the yaml file.
        '''
    
        with open(yaml_file, 'r') as stream:
            try:
                yaml_data = yaml.safe_load(stream)
                
                for action in yaml_data['actions']:
                    if action['type'] == 'RUN_DOCKER_CONTAINER':
                        return action['docker_image_name'] + ":" + action['docker_image_tag']

            except yaml.YAMLError as exc:
                print(exc)


def get_container_prediction_url_from_yaml(yaml_file):
    
        '''
        Get the prediction url from the yaml file.
        '''
    
        with open(yaml_file, 'r') as stream:
            try:
                yaml_data = yaml.safe_load(stream)
                
                for action in yaml_data['actions']:
                    if action['type'] == 'MAKE_PREDICTION':
                        return action['route']

            except yaml.YAMLError as exc:
                print(exc)


def get_container_model_page_urls_from_yaml(yaml_file):
    
        '''
        Get the model page urls from the yaml file.
        '''
    
        with open(yaml_file, 'r') as stream:
            try:
                yaml_data = yaml.safe_load(stream)
                
                for action in yaml_data['actions']:
                    if action['type'] == 'TRAINING':
                        training_url = action['route']
                    if action['type'] == 'GET_TRAINING_DATA':
                        get_training_data_url = action['route']
                    if action['type'] == 'GET_VALIDATION_DATA':
                        get_validation_data_url = action['route']
                    if action['type'] == 'GET_APPROVED_DATA_ANNOTATIONS':
                        get_approved_data_url = action['route']
                    if action['type'] == 'SEND_MODEL_WEIGHTS':
                        send_model_weights_url = action['route']

                return training_url, get_training_data_url, get_validation_data_url, get_approved_data_url, send_model_weights_url

            except yaml.YAMLError as exc:
                print(exc)


def check_if_docker_configuration_yaml_is_valid(yml_file):

    '''
    Function that checks the validity of a docker configuration YAML file.
    '''
    
    with open(str(yml_file), "r") as stream:
        try:
            print(yaml.safe_load(stream))
            return True
        except yaml.YAMLError as exc:
            print(exc)    
            return False
    

def send_audio_to_container_for_preds(audio_file_path, model_name, container_url):

    '''
    Function that sends the prediction data and request to the container.
    '''

    # url = f'http://{CONTAINER_URL}:{CONTAINER_PORT}/predict'
    with open(audio_file_path, 'rb') as file:
        files = {'audio_data': file}
        req = requests.post(container_url, files=files)
    
    return req.json()[f'prediction {model_name}']


def pull_docker_image(dockerhub_repo):

    '''
    Function that runs docker, pulls image for the given dockerhub and runs the container.
    '''

    try:
        client = docker.from_env()
        print("Client ready.")
        image = client.images.pull(dockerhub_repo)
        print("Image pulled.")
        # container = client.containers.run(image, detach=True, ports= {f'{CONTAINER_PORT}/tcp': ({CONTAINER_URL}, int(CONTAINER_PORT))})
        container = client.containers.run(image, detach=True, network_mode='host')
        print(f'Docker {container} started.')
    except:
        print("Problem with image given, anaible to run container.")
        container = None

    return container