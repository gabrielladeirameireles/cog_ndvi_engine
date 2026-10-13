cat << 'EOF' > README.md
# COG NDVI Engine

O COG NDVI Engine (apelidado carinhosamente de Climux) e um sistema web de geoprocessamento e analise de imagens de satelite em tempo real. A aplicacao foi projetada para processar matrizes raster no formato GeoTIFF e Cloud Optimized GeoTIFF (COG), permitindo a visualizacao interativa de indices espectrais, analise estatistica espacial e geracao automatizada de relatorios tecnicos sem a necessidade de pre-renderizar arquivos de imagem gigantescos.

---

## O que o sistema faz

A aplicacao oferece uma plataforma integrada para inspecao e monitoramento ambiental a partir de dados orbitais, cobrindo o ciclo completo desde a leitura dos dados brutos ate a entrega de relatorios executivos.

1. Servidor de Tiles XYZ em Tempo Real
A medida que o usuario navega pelo mapa interativo, a aplicacao realiza a leitura dinamica das bandas espectrais da imagem de satelite (como Sentinel-2). O servidor calcula em tempo real o indice espectral selecionado e aplica a paleta de cores escolhida antes de enviar a imagem fatiada para a interface. Indices suportados:
- NDVI (Normalized Difference Vegetation Index): Avaliacao da saude e densidade da vegetacao.
- NDWI (Normalized Difference Water Index): Delimitacao de corpos d'agua e umidade do solo.
- EVI (Enhanced Vegetation Index): Analise de vegetacao com reducao de ruidos atmosfericos e do solo.

2. Inspecao Pontual de Refletancia
Ao clicar em qualquer ponto do mapa, as coordenadas geograficas (latitude e longitude) sao enviadas ao servidor. O sistema amostra os valores exatos dos pixels na matriz raster e retorna o valor numérico do indice espectral, acompanhado da classificacao da cobertura do solo (por exemplo: Agua, Solo Exposto, Vegetacao Escassa ou Vegetacao Densa).

3. Analise de Regiao de Interesse (ROI)
Atraves de ferramentas de desenho vetorial no mapa, o usuario pode delimitar poligonos ou retangulos em areas especificas. O backend recebe a geometria GeoJSON e executa um mascaramento espacial na imagem raster, calculando:
- Area total da regiao em hectares.
- Estatisticas descritivas: valor medio, minimo, maximo e desvio-padrao do indice.
- Distribuicao percentual das classes de vegetacao na area recortada.
- Histograma de frequencia dos valores de indice.

4. Exportacao de Resultados e Dados
Para suportar tomadas de decisao e auditorias tecnicas, o sistema permite:
- Geracao de relatorio executivo em formato PDF contendo mapas, tabelas formatadas e metadados da analise.
- Download do recorte exato da Regiao de Interesse em formato GeoTIFF, mantendo as referencias de georreferenciamento originais para uso em softwares GIS de bancada (QGIS, ArcGIS).

5. Historico e Persistencia
Todas as analises de ROI realizadas sao armazenadas em um banco de dados relacional para consulta futura, permitindo rever estatisticas e reemitir relatorios a qualquer momento.

---

## Como o sistema funciona (Fluxo Interno de Dados)

1. Requisicao do Cliente: O navegador envia requisicoes HTTP pedindo blocos de mapa (tiles), coordenadas de ponto ou geometrias vetoriais.
2. Camada de Proxy Reverso (Nginx): O Nginx recebe todo o trafego externo na porta 8080 e encaminha as requisicoes com seguranca para a aplicacao FastAPI.
3. Processamento Geospatial (FastAPI + Rasterio/GDAL): O backend abre o arquivo raster, realiza a reprojecao espacial para Web Mercator se necessario, faz o fatiamento matricial com NumPy, calcula as equacoes dos indices e aplica o mapeamento de cores.
4. Resposta e Renderizacao: A imagem da tile ou o payload JSON com dados estatisticos e devolvido ao frontend. O Leaflet atualiza o mapa e o Chart.js desenha os graficos estatisticos em tempo real.
5. Compilacao de Documentos: Quando solicitado o PDF, a biblioteca ReportLab constroi a estrutura do documento no servidor e disponibiliza o arquivo compilado para download.

---

## Arquitetura e Tecnologias

### Backend
- Python 3.10
- FastAPI (Estrutura da API RESTful e rotas de servico)
- Rasterio e GDAL (Manipulacao de arquivos raster, mascaramento por geometria e leitura espacial)
- NumPy (Processamento matricial de alto desempenho para calculo dos indices)
- SQLAlchemy e SQLite (Persistencia de dados e mapeamento objeto-relacional)
- ReportLab (Geracao dinamica de relatorios tecnicos em PDF)

### Frontend
- HTML5, CSS3 e JavaScript Puro (Sem frameworks pesados no cliente)
- Leaflet.js e Leaflet.Draw (Visualizacao cartografica interativa e desenho de geometrias)
- Chart.js (Renderizacao de graficos de distribuicao e histogramas)

### Infraestrutura
- Podman (Gerenciamento e isolamento de conteineres)
- Nginx (Proxy reverso configurado na porta 8080 repassando requisicoes para o servidor Uvicorn na porta 8000)

---

## Estrutura do Projeto

```text
cog_ndvi_engine/
├── data/               # Armazenamento de rasters GeoTIFF e banco de dados SQLite
├── src/
│   ├── api/            # Configuracao e rotas da API FastAPI
│   │   └── routes/     # Endpoints da aplicacao (/ndvi/tiles, /ndvi/roi-stats, etc.)
│   ├── db/             # Conexao SQLite e modelos ORM (SavedROI)
│   ├── services/       # Logica de geoprocessamento e geracao de PDF
│   └── web/            # Interface grafica do usuario (index.html)
├── Dockerfile          # Definicao do container com GDAL e dependencias Python
├── nginx.conf          # Configuracao de proxy reverso do Nginx
├── setup.py            # Script de inicializacao e configuracao
└── README.md           # Documentacao tecnica do projeto


## NOTA SOBRE O DESENVOLVIMENTO

Este projeto foi totalmente desenvolvido, estruturado, testado e publicado utilizando exclusivamente o terminal Linux (Bash), sem o apoio de Ambientes de Desenvolvimento Integrados (IDEs) com interface grafica. A abordagem teve como objetivo explorar um fluxo de trabalho direto via linha de comando, cobrindo a criacao de scripts Python, compilacao de dependencias C geospaciais, orquestracao de conteineres e gerenciamento de versao via Git.
EOF
