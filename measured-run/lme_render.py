"""Session serialization shared by the LongMemEval dev tools (matches the live import)."""


def render(slot, date, turns):
    created = date.split(" ")[0].replace("/", "-")
    head = (
        "---\npromotion: approved\nstatus: active\n"
        f'created: "{created}"\nsource: "imported conversation history"\n'
        'importance: "medium"\nttl: "never"\nprotected: false\n'
        f'tags: ["conversation-history"]\nsource_session_slot: {slot}\n---\n\n'
        f"# Imported conversation session {slot:03d}\n\nOriginal session time: {date}\n"
    )
    body = "".join(
        "**" + t["role"] + ":**\n\n" + t["content"].replace("\r\n", "\n") + "\n\n" for t in turns
    )
    return head + "\n" + body.rstrip() + "\n"
