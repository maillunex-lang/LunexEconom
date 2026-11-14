extends Node
## In-memory account state. No tokens are written to disk.
var access_token: String = ""
var username: String = ""

func sign_in(token: String, name: String) -> void:
    access_token = token
    username = name

func sign_out() -> void:
    access_token = ""
    username = ""

func is_authenticated() -> bool:
    return not access_token.is_empty()
