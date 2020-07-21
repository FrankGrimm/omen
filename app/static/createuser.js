
function setupInviteGeneration() {
    const generateInviteButton = document.getElementById("generateInvite");
    const copyInviteButton = document.getElementById("copyInvite");
    const inviteTextField = document.getElementById("inviteLink");
    if (!generateInviteButton || !inviteTextField) {
        return;
    }
    
    inviteTextField.addEventListener("click", (event) => {
        inviteTextField.setSelectionRange(0, inviteTextField.value.length);
    });

    generateInviteButton.addEventListener("click", (event) => {
        event.preventDefault();

        inviteTextField.value = "Generating...";
        inviteTextField.classList.add("update_active");
    
        const data = {
            action: "generate_invite"
        };
        fetch(window.OMEN_BASE + "user/create", {
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
            .then(inviteResponse => {
                inviteTextField.classList.remove("update_active");
                inviteTextField.classList.add("generated");
                console.log(inviteResponse);
                const inviteURI = window.location.protocol + "//" 
                                  + window.location.host 
                                  + inviteResponse.uri
                                  + `?by=${encodeURIComponent(inviteResponse.by)}`
                                  + `&token=${encodeURIComponent(inviteResponse.token)}`;
                inviteTextField.value = inviteURI;
                if (copyInviteButton) {
                    copyInviteButton.removeAttribute("disabled");
                }
            }).catch((err) => {
                inviteTextField.value = `Invite generation failed (${err}).`;
                inviteTextField.classList.remove("update_active");
                inviteTextField.classList.add("update_failed");
                console.error(err);
            });

        return false;
    });
                
    if (!copyInviteButton) {
        return;
    }
    copyInviteButton.addEventListener("click", (event) => {
        event.preventDefault();
        inviteTextField.focus();
        inviteTextField.setSelectionRange(0, inviteTextField.value.length);
        const copySuccess = document.execCommand('copy');
        inviteTextField.blur();
        inviteTextField.classList.remove("generated");
        return false;
    });
}

window.addEventListener('DOMContentLoaded', (event) => {

    setupInviteGeneration();
});
