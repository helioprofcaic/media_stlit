@echo off
REM Batch script para iniciar o Media Player Desktop (PyQt)

REM Define o título da janela do console
TITLE Media Player Desktop Loader

REM --- Verificação do Ambiente Virtual ---
REM Verifica se a pasta do ambiente virtual (.venv) existe
IF NOT EXIST .venv (
    echo.
    echo [LOADER] Ambiente virtual nao encontrado. Criando...
    
    REM Tenta encontrar o executável do Python
    py -3 -c "import sys" >nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERRO] Python 3 nao encontrado no PATH. Por favor, instale o Python 3.
        pause
        exit /b
    )
    
    REM Cria o ambiente virtual
    py -3 -m venv .venv
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b
    )
    echo [LOADER] Ambiente virtual criado com sucesso.
)

REM --- Ativação e Instalação de Dependências ---
echo.
echo [LOADER] Ativando ambiente virtual e verificando dependencias...

REM Ativa o ambiente virtual
call .\.venv\Scripts\activate.bat

REM Instala as dependências do requirements.txt (se existir)
IF EXIST requirements.txt (
    pip install -r requirements.txt
)

REM --- Execução do Player ---
echo.
echo [LOADER] Iniciando o Player Desktop...
python load_player.py

REM --- Finalização ---
echo.
echo [LOADER] Player finalizado. Pressione qualquer tecla para sair.
pause >nul