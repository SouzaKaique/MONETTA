"""Tradução das mensagens de validação do marshmallow, que vêm em inglês."""
import re

# Mensagens específicas do MONETTA já vêm em português e passam direto.
_RULES = [
    (r"Missing data for required field\.", "Campo obrigatório."),
    (r"Field may not be null\.", "Campo obrigatório."),
    (r"Longer than maximum length (\d+)\.", "Texto muito longo: use no máximo {0} caracteres."),
    (r"Shorter than minimum length (\d+)\.", "Texto muito curto: use pelo menos {0} caracteres."),
    (r"Length must be between (\d+) and (\d+)\.", "Use de {0} a {1} caracteres."),
    (r"Length must be (\d+)\.", "Use exatamente {0} caracteres."),
    (r"Not a valid email address\.", "E-mail inválido."),
    (r"Not a valid URL\.", "Endereço inválido."),
    (r"Not a valid (?:number|decimal|integer)\.", "Número inválido."),
    (r"Not a valid date\.", "Data inválida."),
    (r"Not a valid datetime\.", "Data e hora inválidas."),
    (r"Not a valid (?:string|boolean|UUID|list|mapping)\.", "Valor inválido."),
    (r"Must be one of: .*", "Opção inválida."),
    (r"Must be greater than or equal to (\S+) and less than or equal to (\S+)\.",
     "Use um valor entre {0} e {1}."),
    (r"Must be greater than or equal to (\S+)\.", "Use um valor maior ou igual a {0}."),
    (r"Must be less than or equal to (\S+)\.", "Use um valor menor ou igual a {0}."),
    (r"Must be greater than (\S+)\.", "Use um valor maior que {0}."),
    (r"Unknown field\.", "Campo não reconhecido."),
    (r"Invalid input type\.", "Valor inválido."),
    (r"Invalid value\.", "Valor inválido."),
]
_COMPILED = [(re.compile(f"^{pattern}$"), text) for pattern, text in _RULES]


def translate(message: str) -> str:
    for pattern, text in _COMPILED:
        match = pattern.match(message)
        if match:
            return text.format(*match.groups())
    return message


def translate_all(messages):
    """Percorre a estrutura de erros (dicts e listas aninhados) traduzindo cada texto."""
    if isinstance(messages, dict):
        return {key: translate_all(value) for key, value in messages.items()}
    if isinstance(messages, list):
        return [translate_all(value) for value in messages]
    if isinstance(messages, str):
        return translate(messages)
    return messages
