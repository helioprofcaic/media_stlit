@echo off
setlocal

set "VENV_DIR=.venv"

REM Verifica se o Python esta instalado
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python nao encontrado. Por favor instale o Python.
    pause
    exit /b 1
)

REM Verifica se o ambiente virtual existe
if not exist "%VENV_DIR%" (
    echo Criando ambiente virtual...
    python -m venv "%VENV_DIR%"
)

REM Ativa o ambiente virtual
call "%VENV_DIR%\Scripts\activate"

REM Instala/Atualiza dependencias
echo Verificando dependencias...
pip install -r requirements.txt

REM Nota: Para o Google Drive funcionar, o arquivo de segredos deve estar em .streamlit\secrets.toml
REM Se aparecer um aviso no aplicativo, verifique a localização e o conteúdo deste arquivo.

REM Executa a aplicacao
echo Iniciando Media Player Web...
streamlit run streamlit_app.py

pause
