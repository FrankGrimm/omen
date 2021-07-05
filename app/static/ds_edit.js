
function setACLstatus($elem, elemrole, newroles) {
    console.log("newroles-setacl", newroles);
    // remove icons
    let $icocheck = $elem.find(".fa-check-square");
    if ($icocheck && $icocheck.length) {
        $icocheck.remove();
    }
    let $icosquare = $elem.find(".fa-square");
    if ($icosquare && $icosquare.length) {
        $icosquare.remove();
    }

    if (newroles.indexOf(elemrole) < 0) {
        $elem.addClass("btn-outline-primary");
        $elem.removeClass("btn-outline-success");
        $newi = $('<i class="far fa-square"></i>');
        $elem.text("make " + elemrole + " ");
        $elem.append($newi);
    } else {
        $elem.removeClass("btn-outline-primary");
        $elem.addClass("btn-outline-success");
        $newi = $('<i class="far fa-check-square"></i>');
        $elem.text(elemrole + " ");
        $elem.append($newi);
    }
}

function updateACL(foruser, annoaction, newroles) {
    $("a.toggleacl").each(function(idx, elem) {
        const $elem = $(elem);
        if ($elem.data("userid") != foruser) { return; }

        const elemrole = $elem.data("roleid");
        console.log(elemrole, newroles)
        setACLstatus($elem, elemrole, newroles);
    });
}

function updateSplits(split_action, action_payload) {
    const $split_editor = $("#ds_split_editor");
    
    $split_editor.css("opacity", "0.5");
    $split_editor.find(".ajax-loading").show();


    if (action_payload.splitmethod === "value") {
        // http://localhost:5000/omen/dataset/8/field/user_statuses_count.json
        const field_info_target = API_TARGET_FIELDINFO.replace("{field}", 
                                                               encodeURIComponent(action_payload.splitcolumn));

        fetch(field_info_target, {
            method: 'GET',
            mode: 'cors',
            cache: 'no-cache',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            redirect: 'follow',
            referrerPolicy: 'no-referrer'
        })
        .then(response => response.json())
        .then(fieldinfo => {
            console.log("got fieldinfo", fieldinfo);
            const valuePrompt = bootbox.prompt({
                title: "Split at value:",
                message: "Minimum value: " + fieldinfo.min + "<br> Maximum value: " + fieldinfo.max,
                inputType: 'number',
                callback: function (result) {
                    if (!result) { 
                        $split_editor.css("opacity", "1.0");
                        $split_editor.find(".ajax-loading").hide();
                        return;
                    }
                    action_payload.splitvalue = result;
                    sendUpdatesplits(action_payload);
                }
            });
            valuePrompt.init(function() {
                const targetInput = valuePrompt.find("input");
                if (fieldinfo && fieldinfo.min !== undefined) {
                    targetInput.attr("min", fieldinfo.min);
                }
                if (fieldinfo && fieldinfo.max !== undefined) {
                    targetInput.attr("max", fieldinfo.max);
                }
                console.log(targetInput);
            });

        }).catch((err) => {
            console.error("field info retrieval failed", err);
        });
    } else {
        sendUpdatesplits(action_payload);
    }
}

function sendUpdatesplits(action_payload) {
    jQuery.ajax({
        url: window.location.href,
        data: JSON.stringify({"action": "spliteditor", "options": action_payload || {}}),
        cache: false,
        contentType: "application/json",
        method: 'POST',
        success: function(data){
            document.getElementById("split_editor_container").innerHTML = data;
            initializeSplitEditor();
        },
        error: function(jqXHR, textstatus, err) {
            if (!err) { return; }
            alert(textstatus + " " + err);
        }
    });
}

function updateTags(taskdef_id, tag_action, newtags) {
    newtags = newtags || [];

    console.log("setting new tags", newtags);
    
    $("#tag_editor_" + taskdef_id).css("opacity", "0.5");
    $("#tag_editor_" + taskdef_id).find(".ajax-loading").show();

    jQuery.ajax({
        url: window.location.href,
        data: JSON.stringify({"taskdef_id": taskdef_id,
                              "action": "tageditor",
                              "tagaction": tag_action || "update_taglist",
                              "newtags": newtags}),
        cache: false,
        contentType: "application/json",
        method: 'POST',
        success: function(data){
            document.getElementById("tag_editor_container_" + taskdef_id).innerHTML = data;
            initializeTagEditor();
        },
        error: function(jqXHR, textstatus, err) {
            if (!err) { return; }
            alert(textstatus + " " + err);
        }
    });
}

function updateTagMetadata(taskdef_id, tag_action, current_tag, tag_value) {
    console.log("updating tag metadata", tag_action, current_tag, tag_value);
    
    $("#tag_editor_" + taskdef_id).css("opacity", "0.5");
    $("#tag_editor_" + taskdef_id).find(".ajax-loading").show();

    jQuery.ajax({
        url: window.location.href,
        data: JSON.stringify({"taskdef_id": taskdef_id,
                              "action": "tageditor",
                              "tagaction": tag_action,
                              "tag": current_tag,
                              "value": tag_value}),
        cache: false,
        contentType: "application/json",
        method: 'POST',
        success: function(data){
            document.getElementById("tag_editor_container_" + taskdef_id).innerHTML = data;
            initializeTagEditor();
        },
        error: function(jqXHR, textstatus, err) {
            if (!err) { return; }
            alert(textstatus + " " + err);
        }
    });
}


function getCurrentTags(taskdef_id) {
    const all_tags = [];

    const target_container = document.querySelector("form[data-taskdefid='" + taskdef_id + "']");

    if (!target_container) {
        return null;
    }

    target_container.querySelectorAll("div.tageditor_entry").forEach((elem, idx) => {
        const $elem = $(elem);
        const cur_tag = elem.dataset.tag ? ("" + elem.dataset.tag).trim() : "";
        const cur_position = $elem.data("position");
        const total_tag_count = $elem.data("tagcount");
        all_tags.push( $elem.find("input.tageditor_taginput")[0].value );
    });

    return all_tags;
}

function initializeSplitEditor() {
    $(".ds_split_overview_single").each((idx, elem) => {
        const $elem = $(elem);
        const targetsplit = $elem.data("targetsplit");
        console.log("SPLITEDITOR", idx, $elem, targetsplit);

        // spliteditor_nameinput
        // enable change action if tag has been renamed
        $elem.find("input.spliteditor_nameinput").on("input change", function handleSplitEditorChange() {
            const $changed_input = $(this);
            const $entry = $($changed_input.parents(".ds_split_overview_single")[0]);
            $entry.find("button.split_action_rename").removeAttr("disabled");
        });
        
        $elem.find(".dssplit_change").click((e) => {
            e.preventDefault();
            if (!e.target) { return false; }

            let btn = $(e.target)[0];
            if (btn.tagName.toLowerCase() !== 'button') {
                btn = $(btn).parents(".dssplit_change")[0];
            }
            console.log("split action btn", btn);
            const $btn = $(btn);
            const $entry = $btn.parents(".ds_split_overview_single")[0];
            
            const split_action = $btn.data("splitaction") || null;
            const targetsplit = "" + $btn.data("targetsplit");
            
            console.log("split action", split_action, targetsplit);
            if (!split_action || split_action == "") {
                throw Error("no value for split_action");
            }
            if (!targetsplit === null) {
                throw Error("no value for targetsplit");
            }

            const actionoptions = {
                target: targetsplit,
                splitaction: split_action,
                splitmethod: $btn.data("splitmethod") || null,
                splitcolumn: $btn.data("splitcolumn") || null,
                splitratio: $btn.data("splitratio") || null,
                splitcount: $btn.data("splitcount") || null,
                mergeinto: $btn.data("mergeinto") || null,
                targetuser: $btn.data("targetuser") || null,
                target_new: $elem.find("input.spliteditor_nameinput").val().trim()
            }
            updateSplits(split_action, actionoptions);
            return false;
        });


    });
}

function initializeTagEditor() {
    const target_containers = document.querySelectorAll("form[data-taskdefid]");

    if (!target_containers) {
        console.log("no taskdef containers found")
        return null;
    }

    target_containers.forEach((container) => {
        console.log("initializing task container", container);
        initializeTagEditorContainer(container)
    });
}

function initializeTagEditorContainer(target_container) {
    if (target_container.tag_editor_initialized) {
        console.log("already initialized");
        return;
    }

    target_container.querySelectorAll("div.tageditor_entry").forEach((elem, idx) => {
        const $elem = $(elem);
        const cur_tag = $elem.data("tag");
        const cur_position = $elem.data("position");
        const total_tag_count = $elem.data("tagcount");
        console.log("TAGEDITOR", idx, elem, cur_tag, cur_position, total_tag_count);
        
        // enable change action if tag has been renamed
        $elem.find("input.tageditor_taginput").on("input change", function handleTagEditorChange() {
            const $changed_input = $(this);
            const $entry = $($changed_input.parents("div.tageditor_entry")[0]);
            
            const entry_tag = ("" + $entry.data("tag")).trim();
            const input_tag = $changed_input.val().trim();

            // enable action button if a rename was detected
            let has_change = false;
            if (entry_tag !== input_tag && input_tag.length > 0) {
                $entry.find("button.tageditor_action_rename").removeAttr("disabled");
                has_change = true;
            } else {
                $entry.find("button.tageditor_action_rename").attr("disabled", "disabled");
            }

            // disable changing other tag names while this one has not been applied
            // (this prevents the user from simultaneously changing multiple tags)
            document.querySelectorAll("input.tageditor_taginput").forEach( (other_input) => {
                if (has_change) {
                    if (other_input === $changed_input[0]) { return; }

                    other_input.disabled = true;
                } else {
                    other_input.disabled = false;
                }
            }); 

            console.log("CHANGE", entry_tag, "=>", input_tag);

        });

        $elem.find(".tageditor_action").click((e) => {
            e.preventDefault();
            if (!e.target) { return false; }

            let btn = $(e.target)[0];
            if (btn.tagName.toLowerCase() !== 'button') {
                btn = $(btn).parents(".tageditor_action")[0];
            }
            const $btn = $(btn);
            const $entry = $btn.parents("div.tageditor_entry")[0];
            
            const tag_action = $btn.data("action");
            const tag_value = $btn.data("value") || null;
            const current_tag = $btn.data("tag");

            const taskdef_id = e.target.closest("form").dataset.taskdefid;

            const initial_tags = getCurrentTags(taskdef_id);
            let updated_tags = [...initial_tags];

            const tag_index = updated_tags.indexOf(current_tag);
            let is_metadata_action = false;
            
            console.log("tags action", tag_action);
            if (tag_action === "move_tag_down" && (tag_index < total_tag_count)) {    
                updated_tags[tag_index] = initial_tags[tag_index + 1];
                updated_tags[tag_index + 1] = initial_tags[tag_index];
            } else if (tag_action === "move_tag_up" && (tag_index > 0)) {    
                updated_tags[tag_index] = initial_tags[tag_index - 1];
                updated_tags[tag_index - 1] = initial_tags[tag_index];
            } else if (tag_action === "delete_tag" && updated_tags.indexOf(current_tag) > -1) {
                updated_tags.splice(updated_tags.indexOf(current_tag), 1);
            } else if (tag_action === "rename_tag") {
                // rename is automatically applied in getCurrentTags()
            } else {
                is_metadata_action = true;
            }

            if (!is_metadata_action) {
                console.log("TAGACTION", tag_action, initial_tags, "=>", updated_tags);
                updateTags(taskdef_id, tag_action, updated_tags);
                return false;
            } else {
                updateTagMetadata(taskdef_id, tag_action, current_tag, tag_value);
                return true; // required to close the dropdowns
            }
        });

    });

    const createTagInput = $("input.tageditor_add_tag");
    const createTagButton = $("button.tageditor_add_tag_action");

    createTagInput.on("input change", function handleTagEditorNewTagChange(e) {
        const taskdef_id = e.target.closest("form").dataset.taskdefid;
        const current_tags = getCurrentTags(taskdef_id);
        const new_tag_value = e.target.value.trim();

        if (new_tag_value.length && current_tags.indexOf(new_tag_value) === -1) {
            createTagButton.removeAttr("disabled");
        } else {
            createTagButton.attr("disabled", "disabled");
        }
    });
    createTagButton.on("click", function createNewTag(e) {
        e.preventDefault();
        const containerInput = e.target.closest("form").querySelector("input.tageditor_add_tag");
        const new_tag_value = containerInput.value.trim();
        const taskdef_id = e.target.closest("form").dataset.taskdefid;
        const current_tags = getCurrentTags(taskdef_id);
        current_tags.push(new_tag_value);
        
        console.log("tag::create", current_tags);
        updateTags(taskdef_id, "update_taglist", current_tags);
        return false;
    });
    
    console.log("initializeTagEditor(), current:", getCurrentTags(target_container.dataset.taskdefid));

    target_container.tag_editor_initialized = true;
}

function initializeDataFramePreview() {
    let $tbl = $("#previewdftable");
    if ($tbl) {
        $("#previewdftable tbody tr").each(function() {
            $(this).find("td").wrapInner('<div class="tdwrap">');
        });
    }
}

function confirmDeleteTask(e) {
    e.preventDefault();

    const target_form = e.target.closest("form");
    const target_confirm = target_form.querySelector("input[name='task_delete_confirm']");

    bootbox.confirm({
        title: "Confirm task deletion?",
        message: "Warning: You are about to delete a task.\nData already entered for this task can not be recovered.\nAre you sure?",
        buttons: {
            cancel: {
                label: '<i class="mdi mdi-close"></i> Cancel',
                className: 'btn-default'
            },
            confirm: {
                label: '<i class="mdi mdi-check"></i> Confirm',
                className: 'btn-danger'
            }
        },
        size: "large",
        backdrop: true,
        callback: function (result) {
            if (!result) { return; }

            target_confirm.value = "true";
            target_form.submit();
        }
    });
    return false;
}

function renameTask(e) {
    e.preventDefault();

    const target_form = e.target.closest("form");
    const target_newname = target_form.querySelector("input[name='task_newname']");

    bootbox.prompt({
        title: "Rename task?",
        message: "Please enter a new name for the task '" + target_newname.value + "'",
        value: target_newname.value,
        buttons: {
            cancel: {
                label: '<i class="mdi mdi-close"></i> Cancel',
                className: 'btn-default'
            },
            confirm: {
                label: '<i class="mdi mdi-check"></i> Confirm',
                className: 'btn-primary'
            }
        },
        size: "large",
        backdrop: true,
        callback: function (result) {
            if (!result) { return; }

            target_newname.value = result;
            target_form.submit();
        }
    });
    return false;
}

function setupTaskEditElements() {
    document.querySelectorAll(".taskeditor_delete").forEach(btn => btn.addEventListener("click", confirmDeleteTask));
    document.querySelectorAll(".taskeditor_rename").forEach(btn => btn.addEventListener("click", renameTask));
}

function setupDeleteConfirmation() {
    document.getElementById("form_delete_dataset_confirm").addEventListener("click", function(e) {
        e.preventDefault();
        bootbox.confirm({
            title: "Confirm dataset deletion?",
            message: "Warning: You are about to delete a dataset.\nAre you sure?",
            buttons: {
                cancel: {
                    label: '<i class="mdi mdi-close"></i> Cancel',
                    className: 'btn-default'
                },
                confirm: {
                    label: '<i class="mdi mdi-check"></i> Confirm',
                    className: 'btn-danger'
                }
            },
            size: "large",
            backdrop: true,
            callback: function (result) {
                if (!result) { return; }

                bootbox.confirm({
                    title: "Confirm dataset deletion?",
                    message: "Are you really sure?\nDeleting a dataset cannot be undone.",
                    buttons: {
                        cancel: {
                            label: '<i class="mdi mdi-close"></i> Cancel',
                            className: 'btn-default'
                        },
                        confirm: {
                            label: '<i class="mdi mdi-check"></i> Confirm',
                            className: 'btn-danger'
                        }
                    },
                    size: "large",
                    backdrop: true,
                    callback: function (result) {
                        if (!result) { return; }
                        $("input#confirmation").attr("value", "delete_dataset_confirmed");
                        return $('#form_delete_dataset').submit();
                    }
                });

            }
        });
        
        return false;
    });
}

function sendOptionValue(target, key, newvalue, target_task) {
    console.log("updateOption", key, "=>", newvalue);

    const data = {
        "action": "update_option",
        "option_key": key,
        "option_value": newvalue,
    }
    if (target_task) {
        data["target_task"] = target_task;
        data["action"] = "update_task_option";
    }

    if (target.domLabel) {
        target = target.domLabel;
    }
    target.classList.add("option_update_active");

    fetch(window.OMEN_BASE + "dataset/" + ACTIVE_DATASET_ID + "/edit", {
        method: 'POST',
        mode: 'cors',
        cache: 'no-cache',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json'
        },
        redirect: 'follow',
        referrerPolicy: 'no-referrer',
        body: JSON.stringify(data) 
    })
    .then(response => response.json())
    .then(updateResponse => {
        target.classList.remove("option_update_active");
    }).catch(() => {
        target.classList.remove("option_update_active");
        target.classList.add("option_update_failed");
    });
}

function initOption(cbElem) {
    console.log("initoption", cbElem, cbElem.domLabel);

    const updateOption = (event) => {
        if (event.target.tagName === "LABEL") { return; }
        const opt_newvalue = event.target.checked;
        const opt_key = event.target.value;
        
        let target_task = event.target.closest("input").dataset?.targettask;
        sendOptionValue(event.target, opt_key, opt_newvalue, target_task);
    }

    cbElem.addEventListener("change", updateOption);
    if (cbElem.domLabel) {
        cbElem.domLabel.addEventListener("click", updateOption);
    }
}

function updateAdditionalColumns() {
    const add_col_container = "dataset_admin_taskdef_add_columns";
    const container_dom = document.getElementById(add_col_container);
    console.log("update", ACTIVE_DATASET_ADD_COLUMNS);
   
    if (container_dom) {
        container_dom.innerHTML = '';
    }

    for (let idx = 0; idx < ACTIVE_DATASET_ADD_COLUMNS.length; idx++) {
        const idx_text = ACTIVE_DATASET_ADD_COLUMNS[idx];
        const new_btn = document.createElement("button");
        new_btn.innerHTML = idx_text;
        new_btn.classList.add("btn");
        new_btn.classList.add("btn-sm");
        new_btn.classList.add("btn-info");
        new_btn.classList.add("add_column_remove_button");

        new_btn.addEventListener('click', function(e) {
            e.preventDefault();

            const remove_val = this.textContent;
            if (!remove_val) { return; }

            const remove_index = ACTIVE_DATASET_ADD_COLUMNS.indexOf(remove_val);
            if (remove_index > -1) {
                ACTIVE_DATASET_ADD_COLUMNS.splice(remove_index, 1);
            }

            sendOptionValue(container_dom, "additional_column", ACTIVE_DATASET_ADD_COLUMNS);
            updateAdditionalColumns();
            return false;
        });

        container_dom.appendChild(new_btn);
    }
}

function initAdditionalFieldOption() {
    const fieldSelect = document.getElementById("additional_field_display");
    if (!fieldSelect) { return; }

    console.log("initializing additional field display", fieldSelect);

    function additionalFieldChange() {
        const new_field = (fieldSelect.value && fieldSelect.value !== "-") ? fieldSelect.value : null;
        if (!new_field) { return; }

        console.log("[additional column+]", new_field);
        ACTIVE_DATASET_ADD_COLUMNS.push(new_field);
        console.log("[additional columns]", ACTIVE_DATASET_ADD_COLUMNS);
        sendOptionValue(fieldSelect, "additional_column", ACTIVE_DATASET_ADD_COLUMNS);
		
        console.log("[option remove]", fieldSelect.selectedIndex);
        if (fieldSelect.selectedIndex) {
            fieldSelect.remove(fieldSelect.selectedIndex);
        }
        console.log("[option remove:b]", );
        $(fieldSelect).find("option:selected").remove();
        $(fieldSelect).val('-');
        $(fieldSelect).selectpicker('refresh');

        updateAdditionalColumns();
    }

    fieldSelect.addEventListener("change", additionalFieldChange);
}

function initOptions() {
    document.querySelectorAll(".cb_inspect_option").forEach(initOption);

    initAdditionalFieldOption();
    updateAdditionalColumns();
}

function initLabelAttributes() {
    document.querySelectorAll("label").forEach((labelElem) => {
        if (!labelElem || !labelElem.htmlFor) { return; }
        const domTarget = document.getElementById(labelElem.htmlFor);
        if (!domTarget) { return; }
        
        labelElem.domTarget = domTarget;
        domTarget.domLabel = labelElem;
    });
}

function initUserListButton(btn) {
    btn.addEventListener("click", function() {
        const btn_uid = btn.dataset.userid;
        console.log("add", btn_uid);

        let found_match = false;
        document.querySelectorAll(".userlist_row").forEach((row) => {
            if (row.dataset.userid != btn_uid) {
                return;
            }
            // move matching item to the bottom of the list, right above owner
            const rowParent = row.parentNode;
            row.remove();
            rowParent.insertBefore(row, rowParent.lastElementChild);

            // show matching item
            row.classList.remove("d-none");

            found_match = true;
        });

        if (found_match) {
            btn.classList.add("d-none");
        }

        const remaining_users = [...document.querySelectorAll(".userlist_row")]
                                    .filter(r => r.classList.contains("d-none")).length;
        if (remaining_users === 0) {
            document.getElementById("adduser_to_dataset").setAttribute("disabled", "disabled")
        }

    });
}

function initUserListEditor() {
    document.querySelectorAll(".adduser_btn").forEach(initUserListButton);
}

document.addEventListener("DOMContentLoaded",function(){

    initializeTagEditor();
    initializeSplitEditor();
    initializeDataFramePreview();
    setupDeleteConfirmation();
    setupTaskEditElements();

    $("a.toggleacl").click(function(e) {
        e.preventDefault();
        let $tgt = $(this);

        let $icosquare = $tgt.find(".fa-square");
        let $icocheck = $tgt.find(".fa-check-square");
        
        let annoaction = null;
        let annouser = $tgt.data("userid");
        let annorole = $tgt.data("roleid");
        let $newi = null;

        if ($icosquare && $icosquare.length) {
            annoaction = "add_role";
            $icosquare.remove();
            $newi = $('<i class="far fa-check-square"></i>');
            $tgt.text(annorole + " ");
        }

        if ($icocheck && $icocheck.length) {
            annoaction = "rem_role";
            $icocheck.remove();
            $newi = $('<i class="far fa-square"></i>');
            $tgt.text("make " + annorole + " ");
        }

        $.ajax({
            type: "POST",
            url: $(location).attr("href"),
            data: {"action": annoaction, "annouser": annouser, "annorole": annorole},
            dataType: "html",
            success: function(data) {
                data = JSON.parse(data);
                $tgt.toggleClass("btn-outline-primary");
                $tgt.toggleClass("btn-outline-success");
                $tgt.append($newi);
                
                if (annoaction === "add_role" || annoaction === "rem_role") {
                    updateACL(annouser, annoaction, data.new_roles);
                }
            },
            error: function(jqXHR, textstatus, err) {
                if (!err) { return; }
                alert(textstatus + " " + err);
            }
        });

        return false;
    });


    initLabelAttributes();
    initOptions();
    initUserListEditor();

});

