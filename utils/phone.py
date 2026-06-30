import re

def normalize_phone_to_12_digits(phone: str) -> str:
    """
    Sanitiza e normaliza um número de telefone para o padrão de 12 dígitos da Z-API (55DDXXXXXXXX).
    
    Regras:
    1. Remove todos os caracteres não numéricos.
    2. Garante o DDI '55' no início.
    3. Se o número final tiver 13 dígitos (55DD9XXXXXXXX), remove o nono dígito extra (índice 4),
       retornando exatamente 12 dígitos.
    
    Args:
        phone: String representando o telefone.
        
    Returns:
        String de 12 dígitos contendo apenas números.
    """
    # Remove todos os caracteres não numéricos
    digits = re.sub(r"\D", "", phone)
    
    # Se não começar com 55, adiciona o DDI do Brasil
    if not digits.startswith("55"):
        digits = "55" + digits
        
    # Se tiver 13 dígitos (padrão com o 9 extra), remove o 9 extra.
    # Exemplo: 55 41 9 95252559 -> 13 dígitos
    # O 9 extra fica no índice 4 (0, 1 são '55'; 2, 3 são o DDD; 4 é o '9' extra)
    if len(digits) == 13:
        digits = digits[:4] + digits[5:]
        
    return digits
