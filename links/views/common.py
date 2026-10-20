def form_error(form, error):
    for message in error.messages:
        form.add_error(None, message)
