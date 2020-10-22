function initRevokeButton(btn) {
    btn.addEventListener("click", function(evt) {
        evt.preventDefault();
        
        const reqdata = {
            "action": "revoke_api_token",
            "api_token_id": btn.dataset.tokenid,
        }

        fetch(window.location.href, {
            method: 'POST',
            mode: 'cors',
            cache: 'no-cache',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            redirect: 'follow',
            referrerPolicy: 'no-referrer',
            body: JSON.stringify(reqdata)
        })
        .then(response => response.json())
        .then(response => {
            bootbox.alert({
                title: "Success",
                message: "The token has been revoked",
                onHide: function() {
                    window.location.reload();
                }
            });
        }).catch((err) => {
            console.error(err);
            bootbox.alert("Action failed. Please see log for details.");
        });
        
        return false;
    });
};

function renderTokenDialog(tokenActionResponse) {
    console.log("token action", tokenActionResponse);

    var dialog = bootbox.dialog({
        title: 'Token created',
        message: "<textarea id='new_api_token_result' readonly='readonly' style='width: 100%'>" + tokenActionResponse.token +"</textarea><br>" +
                "<p>Make sure to keep this token confidential and copy it, it cannot be retrieved later.</p>",
        size: 'large',
        backdrop: true,
        onHide: function() {
            window.location.reload();
        },
        buttons: {
            copytoken: {
                label: "Copy to clipboard",
                className: 'btn-success',
                callback: function(){
                    console.log('Custom button clicked');
                    const newtokenElem = document.getElementById("new_api_token_result");
                    newtokenElem.focus();
                    newtokenElem.select();
                    if (!document.execCommand("copy")) {
                        console.error("could not copy token to clipboard");
                        return false;
                    }
                    console.log("token copied");
                    return false;
                }
            },
            ok: {
                label: "Close",
                className: 'btn-info',
                callback: function(){
                    console.log('Custom OK clicked');
                }
            }
        }
    });
}

function initTokenActions() {
    const generateTokenButton = document.getElementById("api_token_generate");
    const generateTokenText = document.getElementById("api_token_generate_description");
   
    // only enable button if a description was given
    generateTokenText.addEventListener("input", function(evt) {
        if (generateTokenText.value.trim() !== "") {
            if (generateTokenButton.hasAttribute("disabled")) {
                generateTokenButton.removeAttribute("disabled");
            }
        } else {
            if (!generateTokenButton.hasAttribute("disabled")) {
                generateTokenButton.setAttribute("disabled", "disabled");
            }
        }
    });

    generateTokenButton.addEventListener("click", function(evt) {
        evt.preventDefault();
        const newTokenDescription = generateTokenText.value;
        if (!newTokenDescription) { return; }

        const reqdata = {
            "action": "new_api_token",
            "api_token_generate_description": newTokenDescription,
        }
        
        fetch(window.location.href, {
            method: 'POST',
            mode: 'cors',
            cache: 'no-cache',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            redirect: 'follow',
            referrerPolicy: 'no-referrer',
            body: JSON.stringify(reqdata)
        })
        .then(response => response.json())
        .then(renderTokenDialog).catch((err) => {
            console.error(err);
            bootbox.alert("Action failed. Please see log for details.");
        });
        
        return false;
    });

    document.querySelectorAll(".revoke_token_btn").forEach(initRevokeButton);
}

document.addEventListener("DOMContentLoaded",function() {
    initTokenActions();
});
