@echo off
cd /d "%~dp0"
echo Montando o app com os produtos ja coletados (sem encartes)...
py -3 -c "from coletor import comparar; from coletor.comum import DADOS, ler_json; b = {m: ler_json(DADOS / f'bruto_{m}.json') for m in ('muffato', 'atacadao', 'amigao', 'condor')}; b = {k: v for k, v in b.items() if v}; print('Mercados:', ', '.join(f'{k} ({len(v)})' for k, v in b.items())); comparar.gerar(b, [], [])"
if errorlevel 1 goto erro
echo.
echo Enviando ao GitHub...
py -3 -m coletor.publicar
if errorlevel 1 goto erro
echo.
echo Pronto! Enviado ao GitHub.
pause
exit /b 0
:erro
echo.
echo Deu erro. Mande um print desta janela.
pause
