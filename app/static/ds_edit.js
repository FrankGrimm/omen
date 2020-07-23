
function setACLstatus($elem, elemrole, newrole) {
    // remove icons
    let $icocheck = $elem.find(".fa-check-square");
    if ($icocheck && $icocheck.length) {
        $icocheck.remove();
    }
    let $icosquare = $elem.find(".fa-square");
    if ($icosquare && $icosquare.length) {
        $icosquare.remove();
    }

    if (!newrole || elemrole !== newrole) {
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

function updateACL(foruser, annoaction, newrole) {
    $("a.toggleacl").each(function(idx, elem) {
        const $elem = $(elem);
        if ($elem.data("userid") != foruser) { return; }
        const elemrole = $elem.data("roleid");

        setACLstatus($elem, elemrole, newrole);

        console.log("updateACL", elem, "elemrole", elemrole, "newrole", newrole);
        if (annoaction === "add_role") {
            if (elemrole === 'curator') {
                if (newrole === 'curator') {
                    console.log("elemrole", elemrole, "show");
                    $elem.show();
                }
            }
            if (elemrole === 'annotator') {
                if (newrole === 'annotator') {
                    console.log("elemrole", elemrole, "show");
                    $elem.show();
                }
            }
        }
    });
}
    
function updateTags(tag_action, newtags) {
    newtags = newtags || [];

    console.log("setting new tags", newtags);
    
    $("#tag_editor").css("opacity", "0.5");
    $("#tag_editor").find(".ajax-loading").show();

    jQuery.ajax({
        url: window.location.href,
        data: JSON.stringify({"action": "tageditor", "tagaction": tag_action || "update_taglist", "newtags": newtags}),
        cache: false,
        contentType: "application/json",
        method: 'POST',
        success: function(data){
            document.getElementById("tag_editor_container").innerHTML = data;
            initializeTagEditor();
        },
        error: function(jqXHR, textstatus, err) {
            if (!err) { return; }
            alert(textstatus + " " + err);
        }
    });
}

function updateTagMetadata(tag_action, current_tag, tag_value) {
    console.log("updating tag metadata", tag_action, current_tag, tag_value);
    
    $("#tag_editor").css("opacity", "0.5");
    $("#tag_editor").find(".ajax-loading").show();

    jQuery.ajax({
        url: window.location.href,
        data: JSON.stringify({"action": "tageditor", "tagaction": tag_action, "tag": current_tag, "value": tag_value}),
        cache: false,
        contentType: "application/json",
        method: 'POST',
        success: function(data){
            document.getElementById("tag_editor_container").innerHTML = data;
            initializeTagEditor();
        },
        error: function(jqXHR, textstatus, err) {
            if (!err) { return; }
            alert(textstatus + " " + err);
        }
    });
}


function getCurrentTags() {
    const all_tags = [];

    $("div.tageditor_entry").each((idx, elem) => {
        const $elem = $(elem);
        const cur_tag = $elem.data("tag").trim();
        const cur_position = $elem.data("position");
        const total_tag_count = $elem.data("tagcount");
        all_tags.push( $elem.find("input.tageditor_taginput")[0].value );
    });

    return all_tags;
}

function initializeTagEditor() {
    $("div.tageditor_entry").each((idx, elem) => {
        const $elem = $(elem);
        const cur_tag = $elem.data("tag");
        const cur_position = $elem.data("position");
        const total_tag_count = $elem.data("tagcount");
        console.log("TAGEDITOR", idx, elem, cur_tag, cur_position, total_tag_count);
        
        // enable change action if tag has been renamed
        $elem.find("input.tageditor_taginput").on("input change", function handleTagEditorChange() {
            const $changed_input = $(this);
            const $entry = $($changed_input.parents("div.tageditor_entry")[0]);
            
            const entry_tag = $entry.data("tag").trim();
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

            const initial_tags = getCurrentTags();
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
                updateTags(tag_action, updated_tags);
                return false;
            } else {
                updateTagMetadata(tag_action, current_tag, tag_value);
                return true; // required to close the dropdowns
            }
        });

    });

    const createTagInput = $("input#tageditor_add_tag");
    const createTagButton = $("button#tageditor_add_tag_action");

    createTagInput.on("input change", function handleTagEditorNewTagChange() {
        const current_tags = getCurrentTags();
        const new_tag_value = createTagInput.val().trim();

        if (new_tag_value.length && current_tags.indexOf(new_tag_value) === -1) {
            createTagButton.removeAttr("disabled");
        } else {
            createTagButton.attr("disabled", "disabled");
        }
    });
    createTagButton.on("click", function createNewTag(e) {
        e.preventDefault();
        const new_tag_value = createTagInput.val().trim();

        const current_tags = getCurrentTags();
        current_tags.push(new_tag_value);

        updateTags("update_taglist", current_tags);
        return false;
    });
    
    console.log("initializeTagEditor(), current:", getCurrentTags());

}

function initializeDataFramePreview() {
    let $tbl = $("#previewdftable");
    if ($tbl) {
        $("#previewdftable tbody tr").each(function() {
            $(this).find("td").wrapInner('<div class="tdwrap">');
        });
    }
}

function setupDeleteConfirmation() {
    document.getElementById("form_delete_dataset_confirm").addEventListener("click", function(e) {
        e.preventDefault();
        if (window.confirm("Warning: You are about to delete a dataset.\nAre you sure?")) {
        if (window.confirm("Are you really sure?\nDeleting a dataset cannot be undone.")) {
            $("input#confirmation").attr("value", "delete_dataset_confirmed");
            return $('#form_delete_dataset').submit();
        }
        }
        return false;
    });
}

function sendOptionValue(target, key, newvalue) {
    console.log("updateOption", key, "=>", newvalue);

    const data = {
        "action": "update_option",
        "option_key": key,
        "option_value": newvalue
    };

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
        
        sendOptionValue(event.target, opt_key, opt_newvalue);
    }

    cbElem.addEventListener("change", updateOption);
    if (cbElem.domLabel) {
        cbElem.domLabel.addEventListener("click", updateOption);
    }
}

function initOptions() {
    document.querySelectorAll(".cb_inspect_option").forEach(initOption);
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
    initializeDataFramePreview();
    setupDeleteConfirmation();

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
            success: function() {
                $tgt.toggleClass("btn-outline-primary");
                $tgt.toggleClass("btn-outline-success");
                $tgt.append($newi);
                
                if (annoaction == "add_role") {
                    updateACL(annouser, annoaction, annorole);
                } else {
                    updateACL(annouser, annoaction, null);
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

