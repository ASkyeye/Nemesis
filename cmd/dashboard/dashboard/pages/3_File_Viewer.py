# Standard Libraries
import base64
import os
import pathlib
import re
import urllib.parse

# 3rd Party Libraries
import extra_streamlit_components as stx
import requests
import streamlit as st
import templates
import utils
from annotated_text import annotated_text, annotation
from streamlit_cookies_manager import CookieManager
from streamlit_elements import (dashboard, editor, elements, html, lazy, mui,
                                sync)

POSTGRES_CONNECTION_URI = os.environ.get("POSTGRES_CONNECTION_URI") or ""
DB_ITERATION_SIZE = os.environ.get("DB_ITERATION_SIZE") or "1000"
NEMESIS_HTTP_SERVER = os.environ.get("NEMESIS_HTTP_SERVER")
PAGE_SIZE = 8


global sources, projects
sources = []
projects = []

current_user = utils.header()

# should be defined in ./packages/python/nemesiscommon/nemesiscommon/contents.py - E_TAG_*
filter_tags = [
    "contains_dpapi",
    "noseyparker_results",
    "parsed_creds",
    "encrypted",
    "deserialization",
    "cmd_execution",
    "remoting",
    "yara_matches",
    "file_canary",
]

if st.session_state["authentication_status"]:
    cookies = CookieManager()
    if not cookies.ready():
        st.stop()

    object_id = ""
    if "object_id" not in st.session_state:
        st.session_state.object_id = None

    triage_pattern = re.compile(r"^triage_(?P<db_id>[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12})_(?P<triage_value>.*)")
    notes_pattern = re.compile(r"^file_notes_(?P<db_id>[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12})$")

    for state in st.session_state:
        triage_matches = triage_pattern.search(state)
        if triage_matches:
            db_id = triage_matches.group("db_id").replace("_", "-")
            triage_value = triage_matches.group("triage_value")
            utils.update_triage_table(db_id, "file_data_enriched", current_user, triage_value)
            del st.session_state[state]
        else:
            notes_matches = notes_pattern.search(state)
            if notes_matches:
                db_id = notes_matches.group("db_id").replace("_", "-")
                utils.update_notes_table(db_id, "file_data_enriched", current_user, st.session_state[state].target.value)
                del st.session_state[state]

    set_search_params = {}
    para = st.experimental_get_query_params()

    for key in para.keys():
        match key:
            case "object_id":
                st.session_state.object_id = para["object_id"][0]
                object_id = st.session_state.object_id

    if not st.session_state.object_id:
        object_id = st.text_input("Enter file object_id")

    if object_id != "":

        if object_id and not re.match(r"^[0-9a-fA-F]{8}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{4}\b-[0-9a-fA-F]{12}$", object_id):
            st.error(f"object_id '{object_id}' is not a valid UUID", icon="🚨")

        elif object_id:
            file = utils.get_file_information(object_id)

            if not((file is None) or len(file) == 0):
                object_id = file["object_id"]
                extension = pathlib.Path(file["name"]).suffix.strip(".").lower()

                # replace - with _ since streamlit doesn't support -'s in session state
                unique_db_id = file["unique_db_id"].replace("-", "_")

                kibana_link = f"{NEMESIS_HTTP_SERVER}/kibana/app/discover#/?_a=(filters:!((query:(match_phrase:(objectId:'{object_id}')))),index:'26360ae8-a518-4dac-b499-ef682d3f6bac')&_g=(time:(from:now-1y%2Fd,to:now))"

                url_enc_file_name = urllib.parse.quote(file["name"])
                download_url = f"http://enrichment-webapi:9910/download/{object_id}"
                pdf_download_url = ""
                extracted_source_download_url = ""
                is_ascii = False
                public_download_url = f"{NEMESIS_HTTP_SERVER}/api/download/{object_id}?name={url_enc_file_name}&action=download"

                if "magic_type" in file and file["magic_type"] and ("ASCII text" in file["magic_type"] or "Unicode text" in file["magic_type"]):
                    is_ascii = True
                if "converted_pdf_id" in file and file["converted_pdf_id"] != "00000000-0000-0000-0000-000000000000":
                    pdf_download_url = f"http://enrichment-webapi:9910/download/{file['converted_pdf_id']}"
                if "extracted_source_id" in file and file["extracted_source_id"] != "00000000-0000-0000-0000-000000000000":
                    extracted_source_download_url = f"http://enrichment-webapi:9910/download/{file['extracted_source_id']}"
                if file["name"].endswith(".pdf"):
                    pdf_download_url = download_url

                tabs = [
                    stx.TabBarItemData(id="basic_file_info", title="Basic File Info", description="Basic File Information"),
                    stx.TabBarItemData(id="elasticsearch_info", title="Elasticsearch Info", description="Elasticsearch Information Dump")
                ]

                es_results = utils.elastic_file_search(object_id)
                has_np_results = False
                if es_results and es_results["hits"]["total"]["value"] == 1:
                    if "noseyparker" in es_results["hits"]["hits"][0]["_source"]:
                        tabs.append(stx.TabBarItemData(id="noseyparker_results", title="Noseyparker Results", description="Noseyparker Results"))

                if pdf_download_url:
                    tabs.append(stx.TabBarItemData(id="pdf_viewer", title="PDF Viewer", description="PDF View of the File"))
                if is_ascii:
                    tabs.append(stx.TabBarItemData(id="file_view", title="File View", description="View of File Data"))

                chosen_tab = stx.tab_bar(
                    data=tabs,
                    default="basic_file_info",
                )

                if chosen_tab == "basic_file_info":
                    layout = [
                        # Grid layout parameters: element_identifier, x_pos, y_pos, width, height, [item properties...]
                        dashboard.Item("1", 0, 0, 10, 2.5, isDraggable=False, isResizable=False, sx={"height": "100%"}),
                    ]
                    with elements("dashboard"):
                        with dashboard.Grid(layout=layout):
                            with mui.Card(
                                key="1",
                                sx={
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "borderRadius": 2,
                                    "overflow": "auto",
                                    "overflowY": "auto",
                                    "m": "10",
                                    "gap": "10px",
                                },
                                padding=1,
                                elevation=1,
                                spacing=10,
                            ):
                                with mui.AppBar(position="sticky", variant="h7", sx={"minHeight": 32}):
                                    with mui.Toolbar(variant="dense", sx={"minHeight": 48, "height": 48}):
                                        mui.Typography(file["name"])
                                        with mui.Tooltip(title="Download the file"):
                                            with html.span:
                                                mui.IconButton(mui.icon.Download, href=public_download_url)
                                        with mui.Tooltip(title="View the file in Kibana"):
                                            with html.span:
                                                mui.IconButton(mui.icon.Search, href=kibana_link, target="_blank")
                                        if extracted_source_download_url:
                                            with mui.Tooltip(title="Download the extracted source code"):
                                                with html.span:
                                                    mui.IconButton(mui.icon.Code, href=extracted_source_download_url, target="_blank")

                                        mui.Box(sx={"flexGrow": 1})

                                        with mui.Tooltip(title="Mark file as useful"):
                                            with html.span:
                                                mui.IconButton(mui.icon.ThumbUpOffAlt, onClick=sync(f"triage_{unique_db_id}_useful"))
                                        with mui.Tooltip(title="Mark file as not useful"):
                                            with html.span:
                                                mui.IconButton(mui.icon.ThumbDownOffAlt, onClick=sync(f"triage_{unique_db_id}_notuseful"))
                                        with mui.Tooltip(title="Mark file as needing additional investigation"):
                                            with html.span:
                                                mui.IconButton(mui.icon.QuestionMark, onClick=sync(f"triage_{unique_db_id}_unknown"))
                                        if file["triage"]:
                                            with html.span:
                                                mui.Typography("triage")

                                # Information table
                                with mui.CardContent(sx={"flex": 1}):
                                    with mui.TableContainer(sx={"maxHeight": 200}):
                                        with mui.Table(size="small", overflowX="hidden", whiteSpace="nowrap"):
                                            with mui.TableBody():
                                                identifier_style = {
                                                    "fontWeight": "bold",
                                                    "borderRight": "1px solid",
                                                    "whiteSpace": "nowrap",
                                                    "padding": "0px 5px 0px 0px",
                                                }

                                                with mui.TableRow(hover=True, padding="none"):
                                                    mui.TableCell("Path", size="small", sx=identifier_style)
                                                    mui.TableCell(file["path"], width="100%")
                                                with mui.TableRow(hover=True, padding="none"):
                                                    if file['source']:
                                                        mui.TableCell("Source / Timestamp", size="small", sx=identifier_style)
                                                        mui.TableCell(f"{file['source']} @ {file['timestamp']}", size="small")
                                                    else:
                                                        mui.TableCell("Timestamp", size="small", sx=identifier_style)
                                                        mui.TableCell(f"{file['timestamp']}", size="small")
                                                with mui.TableRow(hover=True, padding="none"):
                                                    mui.TableCell("Size", sx=identifier_style)
                                                    mui.TableCell(f"{file['size']}")
                                                with mui.TableRow(hover=True, padding="none"):
                                                    mui.TableCell("SHA1 hash", sx=identifier_style)
                                                    mui.TableCell(file["sha1"])
                                                with mui.TableRow(hover=True, padding="none"):
                                                    mui.TableCell("Magic Type", sx=identifier_style)
                                                    mui.TableCell(file["magic_type"])
                                                if file["tags"]:
                                                    with mui.TableRow(hover=True, padding="none"):
                                                        mui.TableCell("Tags", sx=identifier_style)
                                                        with mui.TableCell():
                                                            # Tags
                                                            for tag in file["tags"]:
                                                                mui.Chip(label=tag, color="primary")
                                    # Notes
                                    mui.Typography("Comments:")
                                    with mui.Box(sx={"flexGrow": 1}):
                                        end = mui.IconButton(mui.icon.Save, onClick=sync())

                                        mui.TextField(
                                            # label="Input Any Notes Here",
                                            key=f"file_notes_{unique_db_id}",
                                            defaultValue=file["notes"],
                                            variant="outlined",
                                            margin="none",
                                            multiline=True,
                                            onChange=lazy(sync(f"file_notes_{unique_db_id}")),
                                            fullWidth=True,
                                            sx={"flexGrow": 1},
                                            InputProps={"endAdornment": end},
                                        )

                elif chosen_tab == "noseyparker_results":
                    if es_results != {}:
                        total_hits = es_results["hits"]["total"]["value"]
                        num_results = len(es_results["hits"]["hits"])
                        if total_hits > 0:
                            for i in range(num_results):
                                object_id = es_results["hits"]["hits"][i]["_source"]["objectId"]
                                file_name = es_results["hits"]["hits"][i]["_source"]["name"]
                                download_url = f"{NEMESIS_HTTP_SERVER}/api/download/{object_id}?name={file_name}"
                                kibana_link = f"{NEMESIS_HTTP_SERVER}/kibana/app/discover#/?_a=(filters:!((query:(match_phrase:(objectId:'{object_id}')))),index:'26360ae8-a518-4dac-b499-ef682d3f6bac')&_g=(time:(from:now-1y%2Fd,to:now))"
                                path = es_results["hits"]["hits"][i]["_source"]["path"]
                                sha1 = es_results["hits"]["hits"][i]["_source"]["hashes"]["sha1"]
                                source = ""
                                if "metadata" in es_results["hits"]["hits"][i]["_source"] and "source" in es_results["hits"]["hits"][i]["_source"]["metadata"]:
                                    source = es_results["hits"]["hits"][i]["_source"]["metadata"]["source"]

                                if source:
                                    expander_text = f"{source} : **{path}** (SHA1: {sha1})"
                                else:
                                    expander_text = f"**{path}** (SHA1: {sha1})"

                                for ruleMatch in es_results["hits"]["hits"][i]["_source"]["noseyparker"]["ruleMatches"]:
                                    for match in ruleMatch["matches"]:
                                        if "matching" in match["snippet"]:
                                            rule_name = match["ruleName"]

                                            if "before" in match["snippet"]:
                                                before = match["snippet"]["before"].replace("\n\t", " ")
                                            else:
                                                before = ""

                                            matching = match["snippet"]["matching"]

                                            if "after" in match["snippet"]:
                                                after = match["snippet"]["after"].replace("\n\t", " ")
                                            else:
                                                after = ""

                                            st.write(f"<b>Rule</b>: {rule_name}", unsafe_allow_html=True)
                                            annotated_text(annotation(before, "context", color="#8ef"), annotation(matching, "match"), annotation(after, "context", color="#8ef"))
                                            st.divider()

                elif chosen_tab == "file_view":
                    with elements("file_view"):
                        response = requests.get(download_url)
                        if response.status_code != 200:
                            st.error(f"Error retrieving text data from {download_url}, status code: {response.status_code}", icon="🚨")
                        else:
                            with mui.Card(
                                sx={
                                    "display": "flex",
                                    "overflow": "auto",
                                    "overflowY": "auto",
                                },
                                padding=1,
                                elevation=1,
                                spacing=10,
                            ):
                                editor.Monaco(
                                    height=600,
                                    defaultValue=response.content.decode('utf-8'),
                                    language=utils.map_extension_to_monaco_language(extension)
                                )

                elif chosen_tab == "pdf_viewer":
                    with elements("pdf_viewer"):
                        try:
                            response = requests.get(pdf_download_url)
                            if response.status_code != 200:
                                st.error(f"Error retrieving PDF data from {pdf_download_url}, status code: {response.status_code}", icon="🚨")
                            else:
                                with mui.Card(
                                    sx={
                                        "display": "flex",
                                        "overflow": "auto",
                                        "overflowY": "auto",
                                    },
                                    padding=1,
                                    elevation=1,
                                    spacing=10,
                                ):
                                    b64_data = base64.b64encode(response.content).decode('utf-8')
                                    html.iframe(
                                        src=f"data:application/pdf;base64,{b64_data}",
                                        height="700",
                                        width="100%",
                                        type="application/pdf"
                                    )
                        except Exception as e:
                            st.error(f"Error retrieving PDF data from {pdf_download_url} : {e}", icon="🚨")

                elif chosen_tab == "elasticsearch_info":
                    if es_results != {}:
                        total_hits = es_results["hits"]["total"]["value"]
                        if total_hits == 0:
                            st.warning("No results found in Elasticsearch!")
                        elif total_hits == 1:
                            st.subheader("Elasticsearch Data")
                            st.json(es_results["hits"]["hits"][0])
                        else:
                            st.warning("Too many results found in Elasticsearch!")
