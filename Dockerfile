FROM python:3.7-stretch
WORKDIR ./

RUN apt-get -y install wget ca-certificates gcc && pip3 install --upgrade pip
RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ stretch-pgdg main" >> /etc/apt/sources.list.d/pgdg.list' && apt-get update && apt-get -y install postgresql-client

COPY ./requirements.txt /tmp/requirements.txt
RUN pip3 --no-cache-dir install wheel
RUN pip3 --no-cache-dir install -r /tmp/requirements.txt

RUN python3 -m spacy download en

RUN useradd --create-home omenuser
WORKDIR /home/omenuser
USER omenuser

COPY ./app ./app/
COPY ./config.json ./app/

WORKDIR /home/omenuser/app
ENV FLASK_APP web.py
ENV FLASK_DEBUG 1
ENV FLASK_RUN_HOST 0.0.0.0
ENV FLASK_SKIP_DOTENV 1
EXPOSE 5000
CMD ["flask", "run", "-p", "5000"]
