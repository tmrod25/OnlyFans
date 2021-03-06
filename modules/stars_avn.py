import requests
from modules.helpers import get_directory, json_request, reformat, format_directory, format_media_set, export_archive, format_image, check_for_dupe_file, setup_logger

import os
import json
from itertools import count, product
from itertools import chain
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import logging
import math
from random import randrange

log_download = setup_logger('downloads', 'downloads.log')
log_error = setup_logger('errors', 'errors.log')

# Open config.json and fill in OPTIONAL information
path = os.path.join('settings', 'config.json')
json_config = json.load(open(path))
json_global_settings = json_config["settings"]
multithreading = json_global_settings["multithreading"]
json_settings = json_config["supported"]["stars_avn"]["settings"]
auto_choice = json_settings["auto_choice"]
j_directory = get_directory(json_settings['directory'])
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
ignored_keywords = json_settings["ignored_keywords"]
ignore_unfollowed_accounts = json_settings["ignore_unfollowed_accounts"]
export_metadata = json_settings["export_metadata"]
blacklist_name = json_settings["blacklist_name"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length


def start_datascraper(session, identifier, site_name, app_token, choice_type=None):
    print("Scrape Processing")
    info = link_check(session, app_token, identifier)
    if not info["subbed"]:
        print(info["user"])
        print("First time? Did you forget to edit your config.json file?")
        return [False, []]
    user = info["user"]
    is_me = user["is_me"]
    post_counts = info["count"]
    user_id = str(user["id"])
    username = user["username"]
    print("Name: "+username)
    api_array = scrape_choice(user_id, app_token, post_counts, is_me)
    api_array = format_options(api_array, "apis")
    apis = api_array[0]
    api_string = api_array[1]
    if not json_settings["auto_scrape_apis"]:
        print("Apis: "+api_string)
        value = int(input().strip())
    else:
        value = 0
    if value:
        apis = [apis[value]]
    else:
        apis.pop(0)
    prep_download = []
    for item in apis:
        print("Type: "+item[2])
        only_links = item[1][3]
        post_count = str(item[1][4])
        item[1].append(username)
        item[1].pop(3)
        api_type = item[2]
        results = media_scraper(
            session, site_name, only_links, *item[1], api_type, app_token)
        for result in results[0]:
            if not only_links:
                media_set = result
                if not media_set["valid"]:
                    continue
                directory = results[1]
                location = result["type"]
                prep_download.append(
                    [media_set["valid"], session, directory, username, post_count, location])
    # When profile is done scraping, this function will return True
    print("Scrape Completed"+"\n")
    return [True, prep_download]


def link_check(session, app_token, identifier):
    link = 'https://stars.avn.com/api2/v2/users/' + str(identifier)
    y = json_request(session, link)
    temp_user_id2 = dict()
    y["is_me"] = False
    if not y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = "No users found"
        return temp_user_id2
    if "error" in y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = y["error"]["message"]
        return temp_user_id2
    now = datetime.utcnow().date()
    result_date = datetime.utcnow().date()
    if "email" not in y:
        subscribedByData = y
        # if subscribedByData:
        # expired_at = subscribedByData["expiredAt"]
        # result_date = datetime.fromisoformat(
        #     expired_at).replace(tzinfo=None).date()
        if y["followedBy"]:
            subbed = True
        elif y["subscribedBy"]:
            subbed = True
        elif y["subscribedOn"]:
            subbed = True
        # elif y["subscribedIsExpiredNow"] == False:
        #     subbed = True
        elif result_date >= now:
            subbed = True
        else:
            subbed = False
    else:
        subbed = True
        y["is_me"] = True
    if not subbed:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = "You're not subscribed to the user"
        return temp_user_id2
    else:
        temp_user_id2["subbed"] = True
        temp_user_id2["user"] = y
        temp_user_id2["count"] = [y["postsCount"], [
            y["photosCount"], y["videosCount"]]]
        return temp_user_id2


def scrape_choice(user_id, app_token, post_counts, is_me):
    post_count = post_counts[0]
    media_counts = post_counts[1]
    x = ["Images", "Videos"]
    x = dict(zip(x, media_counts))
    x = [k for k, v in x.items() if v != 0]
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos')
        input_choice = input().strip()
    message_api = "https://stars.avn.com/api2/v2/chats/"+user_id + \
        "/messages?limit=50"
    mass_messages_api = "https://stars.avn.com/api2/v2/chats/"+user_id + \
        "/messages?limit=50"
    stories_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/stories/?limit=10&marker=&offset=0"
    hightlights_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/stories/collections/?limit=10&marker=&offset=0"
    post_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/posts/?limit=10&marker=&offset=0"
    archived_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/stories/collections/?limit=10&marker=&offset=0"
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [j_directory, only_links]
    y = ["photo", "video", "stream", "gif", "audio"]
    s_array = ["You have chosen to scrape {}", [
        stories_api, x, *mandatory, post_count], "Stories"]
    h_array = ["You have chosen to scrape {}", [
        hightlights_api, x, *mandatory, post_count], "Highlights"]
    p_array = ["You have chosen to scrape {}", [
        post_api, x, *mandatory, post_count], "Posts"]
    mm_array = ["You have chosen to scrape {}", [
        mass_messages_api, x, *mandatory, post_count], "Mass Messages"]
    m_array = ["You have chosen to scrape {}", [
        message_api, x, *mandatory, post_count], "Messages"]
    array = [s_array, h_array, p_array]
    new = dict()
    for xxx in array:
        new["api_message"] = xxx[0]
        new["api_array"] = xxx[1]
        new["api_type"] = xxx[2]
        print
    # array = [mm_array]
    # if not is_me:
    #     del array[4]
    valid_input = False
    if input_choice == "a":
        valid_input = True
        a = []
        for z in x:
            if z == "Images":
                a.append([z, [y[0]]])
            if z == "Videos":
                a.append([z, y[1:4]])
        for item in array:
            item[0] = array[0][0].format("all")
            item[1][1] = a
    if input_choice == "b":
        name = "Images"
        for item in array:
            item[0] = item[0].format(name)
            item[1][1] = [[name, [y[0]]]]
        valid_input = True
    if input_choice == "c":
        name = "Videos"
        for item in array:
            item[0] = item[0].format(name)
            item[1][1] = [[name, y[1:4]]]
        valid_input = True
    if valid_input:
        return array
    else:
        print("Invalid Choice")
    return []


def media_scraper(session, site_name, only_links, link, locations, directory, api_count, username, api_type, app_token):
    seperator = " | "
    master_set = []
    media_set = []
    original_link = link
    for location in locations:
        pool = ThreadPool()
        link = original_link
        print("Scraping ["+str(seperator.join(location[1])) +
              "]. Should take less than a minute.")
        array = format_directory(
            j_directory, site_name, username, location[0], api_type)
        user_directory = array[0]
        location_directory = array[2][0][1]
        metadata_directory = array[1]
        directories = array[2]+[location[1]]
        if not master_set:

            if api_type == "Posts":
                ceil = math.ceil(api_count / 100)
                a = list(range(ceil))
                for b in a:
                    b = b * 100
                    master_set.append(link.replace(
                        "offset=0", "offset=" + str(b)))
            if api_type == "Archived":
                ceil = math.ceil(api_count / 100)
                a = list(range(ceil))
                for b in a:
                    b = b * 100
                    master_set.append(link.replace(
                        "offset=0", "offset=" + str(b)))

            def xmessages(link):
                f_offset_count = 0
                while True:
                    y = json_request(session, link)
                    if "list" in y:
                        if y["list"]:
                            master_set.append(link)
                            if y["hasMore"]:
                                f_offset_count2 = f_offset_count+100
                                f_offset_count = f_offset_count2-100
                                link = link.replace(
                                    "offset=" + str(f_offset_count), "offset=" + str(f_offset_count2))
                                f_offset_count = f_offset_count2
                            else:
                                break
                        else:
                            break
                    else:
                        break

            def process_chats(subscriber):
                fool = subscriber["withUser"]
                fool_id = str(fool["id"])
                link_2 = "https://onlyfans.com/api2/v2/chats/"+fool_id + \
                    "/messages?limit=100&offset=0&order=desc&app-token="+app_token+""
                xmessages(link_2)
            if api_type == "Messages":
                xmessages(link)
            if api_type == "Mass Messages":
                messages = []
                offset_count = 0
                while True:
                    y = json_request(session, link)
                    if y:
                        messages.append(y)
                        offset_count2 = offset_count+99
                        offset_count = offset_count2-99
                        link = link.replace(
                            "offset=" + str(offset_count), "offset=" + str(offset_count2))
                        offset_count = offset_count2
                    else:
                        break
                messages = list(chain(*messages))
                message_count = 0

                def process_mass_messages(message, limit):
                    text = message["textCropped"].replace("&", "")
                    link_2 = "https://onlyfans.com/api2/v2/chats?limit="+limit+"&offset=0&filter=&order=activity&query=" + \
                        text+"&app-token="+app_token
                    y = json_request(session, link_2)
                    return y
                limit = "10"
                if len(messages) > 99:
                    limit = "2"
                subscribers = pool.starmap(process_mass_messages, product(
                    messages, [limit]))
                subscribers = [
                    item for sublist in subscribers for item in sublist["list"]]
                seen = set()
                subscribers = [x for x in subscribers if x["withUser"]
                               ["id"] not in seen and not seen.add(x["withUser"]["id"])]
                x = pool.starmap(process_chats, product(
                    subscribers))
            if api_type == "Stories":
                master_set.append(link)
            if api_type == "Highlights":
                r = json_request(session, link)
                if "error" in r:
                    break
                for item in r["list"]:
                    link2 = "https://stars.avn.com/api2/v2/stories/collections/" + \
                        str(item["id"])
                    master_set.append(link2)
        x = pool.starmap(scrape_array, product(
            master_set, [session], [directories], [username], [api_type]))
        results = format_media_set(location[0], x)
        seen = set()
        results["valid"] = [x for x in results["valid"]
                            if x["filename"] not in seen and not seen.add(x["filename"])]
        if results["valid"]:
            os.makedirs(directory, exist_ok=True)
            os.makedirs(location_directory, exist_ok=True)
            if export_metadata:
                os.makedirs(metadata_directory, exist_ok=True)
                archive_directory = metadata_directory+location[0]
                export_archive(results, archive_directory)
        media_set.append(results)

    return [media_set, directory]


def scrape_array(link, session, directory, username, api_type):
    media_set = [[], []]
    media_type = directory[1]
    count = 0
    found = False
    y = json_request(session, link)
    if "error" in y:
        return media_set
    x = 0
    if api_type == "Highlights":
        y = y["stories"]
    y = y["list"] if "list" in y else y
    master_date = "01-01-0001 00:00:00"
    for media_api in y:
        if api_type == "Mass Messages":
            media_user = media_api["fromUser"]
            media_username = media_user["username"]
            if media_username != username:
                continue
        new_api = (media_api["media"] if "media" in media_api else [media_api])
        for media in new_api:
            date = "-001-11-30T00:00:00+00:00"
            size = 1
            src = media["src"]
            link = src["source"]
            date = media_api["createdAt"] if "createdAt" in media_api else media_api["postedAt"]
            if not link:
                continue
            new_dict = dict()
            new_dict["post_id"] = media_api["id"]
            new_dict["link"] = link
            if date == "-001-11-30T00:00:00+00:00":
                date_string = master_date
                date_object = datetime.strptime(
                    master_date, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = datetime.fromisoformat(date)
                date_string = date_object.replace(tzinfo=None).strftime(
                    "%d-%m-%Y %H:%M:%S")
                master_date = date_string
            media["mediaType"] = media["mediaType"] if "mediaType" in media else media["type"]
            if media["mediaType"] not in media_type:
                x += 1
                continue
            if "text" not in media_api:
                media_api["text"] = ""
            new_dict["text"] = media_api["text"] if media_api["text"] else ""
            new_dict["postedAt"] = date_string
            media_id = media["id"] if "id" in media else None
            media_id = media_id if isinstance(media_id, int) else None
            file_name = link.rsplit('/', 1)[-1]
            file_name, ext = os.path.splitext(file_name)
            ext = ext.__str__().replace(".", "").split('?')[0]
            file_path = reformat(directory[0][1], media_id, file_name,
                                 new_dict["text"], ext, date_object, username, format_path, date_format, text_length, maximum_length)
            new_dict["directory"] = directory[0][1]
            new_dict["filename"] = file_path.rsplit('/', 1)[-1]
            new_dict["size"] = size
            if size == 0:
                media_set[1].append(new_dict)
                continue
            media_set[0].append(new_dict)
    return media_set


def download_media(media_set, session, directory, username, post_count, location):
    def download(media, session, directory, username):
        count = 0
        while count < 11:
            link = media["link"]
            r = json_request(session, link, "HEAD", True, False)
            if not r:
                return False

            header = r.headers
            content_length = int(header["content-length"])
            date_object = datetime.strptime(
                media["postedAt"], "%d-%m-%Y %H:%M:%S")
            og_filename = media["filename"]
            media["ext"] = os.path.splitext(og_filename)[1]
            media["ext"] = media["ext"].replace(".", "")
            download_path = media["directory"]+media["filename"]
            timestamp = date_object.timestamp()
            if not overwrite_files:
                if check_for_dupe_file(download_path, content_length):
                    return
            r = json_request(session, link, "GET", True, False)
            if not r:
                return False
            delete = False
            try:
                with open(download_path, 'wb') as f:
                    delete = True
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
            except (ConnectionResetError) as e:
                if delete:
                    os.unlink(download_path)
                log_error.exception(e)
                count += 1
                continue
            except Exception as e:
                if delete:
                    os.unlink(download_path)
                log_error.exception(str(e) + "\n Tries: "+str(count))
                count += 1
                # input("Enter to continue")
                continue
            format_image(download_path, timestamp)
            log_download.info("Link: {}".format(link))
            log_download.info("Path: {}".format(download_path))
            return True
    print("Download Processing")
    print("Name: "+username+" | Directory: " + directory)
    print("Downloading "+str(len(media_set))+" "+location+"\n")
    if multithreading:
        pool = ThreadPool()
    else:
        pool = ThreadPool(1)
    pool.starmap(download, product(
        media_set, [session], [directory], [username]))


def create_session(user_agent, app_token, auth_array):
    me_api = []
    auth_count = 1
    auth_version = "(V1)"
    count = 1
    try:
        auth_cookies = [
        ]
        while auth_count < 3:
            if auth_count == 2:
                auth_version = "(V2)"
                if auth_array["sess"]:
                    del auth_cookies[2]
                count = 1
            session = requests.Session()
            print("Auth "+auth_version+" Attempt "+str(count)+"/"+"10")
            max_threads = multiprocessing.cpu_count()
            session.mount(
                'https://', requests.adapters.HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
            session.headers = {
                'User-Agent': user_agent, 'Referer': 'https://stars.avn.com/'}
            if auth_array["sess"]:
                found = False
                for auth_cookie in auth_cookies:
                    if auth_array["sess"] == auth_cookie["value"]:
                        found = True
                        break
                if not found:
                    auth_cookies.append(
                        {'name': 'sess', 'value': auth_array["sess"], 'domain': '.stars.avn.com'})
            for auth_cookie in auth_cookies:
                session.cookies.set(**auth_cookie)
            while count < 11:

                link = "https://stars.avn.com/api2/v2/users/me"
                r = json_request(session, link)
                count += 1
                if not r:
                    auth_cookies = []
                    continue
                me_api = r
                if 'error' in r:
                    error = r["error"]
                    error_message = r["error"]["message"]
                    if error["code"] == 101:
                        error_message = "Blocked by 2FA."
                    print(error_message)
                    if "token" in error_message:
                        break
                    continue
                else:
                    print("Welcome "+r["name"])
                option_string = "username or profile link"
                array = dict()
                array["session"] = session
                array["option_string"] = option_string
                array["subscriber_count"] = r["followingCount"]
                array["me_api"] = me_api
                return array
            auth_count += 1
    except Exception as e:
        log_error.exception(e)
        # input("Enter to continue")
    array = dict()
    array["session"] = None
    array["me_api"] = me_api
    return array


def get_subscriptions(session, app_token, subscriber_count, me_api, auth_count=0):
    link = "https://stars.avn.com/api2/v2/subscriptions/following/?limit=10&marker=&offset=0"
    r = json_request(session, link)
    if not r:
        return None
    for x in r["list"]:
        x["auth_count"] = auth_count
    return r["list"]


def format_options(array, choice_type):
    string = ""
    names = []
    array = [{"auth_count": -1, "username": "All"}]+array
    name_count = len(array)
    if "usernames" == choice_type:
        if name_count > 1:

            count = 0
            for x in array:
                name = x["username"]
                string += str(count)+" = "+name
                names.append([x["auth_count"], name])
                if count+1 != name_count:
                    string += " | "

                count += 1
    if "apis" == choice_type:
        count = 0
        names = array
        for api in array:
            if "username" in api:
                name = api["username"]
            else:
                name = api[2]
            string += str(count)+" = "+name
            if count+1 != name_count:
                string += " | "

            count += 1
    return [names, string]
