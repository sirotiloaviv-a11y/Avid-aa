/* AI coach chat. Posts to /api/ai/coach and appends the reply. */
(function () {
  "use strict";
  var chat = document.getElementById("chat");
  var form = document.getElementById("chat-form");
  if (!chat || !form) return;

  var input = document.getElementById("chat-input");
  var submit = form.querySelector('button[type="submit"]');

  function bubble(role, text) {
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-" + role;
    var body = document.createElement("div");
    body.className = "chat-bubble";
    body.textContent = text;
    wrap.appendChild(body);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function typing() {
    var wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg-assistant";
    wrap.innerHTML =
      '<div class="chat-bubble"><span class="chat-typing"><span></span><span></span><span></span></span></div>';
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function send(question) {
    if (!question.trim()) return;
    bubble("user", question);
    input.value = "";
    submit.disabled = true;
    var pending = typing();

    window.fp
      .request(chat.getAttribute("data-endpoint"), { method: "POST", body: { question: question } })
      .then(function (data) {
        pending.remove();
        bubble("assistant", data.answer || "לא התקבלה תשובה.");
      })
      .catch(function (error) {
        pending.remove();
        bubble("assistant", error.message || "אירעה שגיאה. נסו שוב.");
      })
      .finally(function () {
        submit.disabled = false;
        input.focus();
      });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(input.value);
  });

  document.querySelectorAll("[data-suggestion]").forEach(function (chip) {
    chip.addEventListener("click", function () {
      send(chip.getAttribute("data-suggestion"));
    });
  });

  chat.scrollTop = chat.scrollHeight;
})();
