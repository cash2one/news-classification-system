# coding:utf-8

import os
from gensim import corpora
from gensim.models.ldamodel import LdaModel
from collections import defaultdict
from myutils import ArticleDB, Dumper, StopWord, ArticleDumper
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import ward, linkage, dendrogram
from myutils import ArticleDB
from treelib import Node, Tree
from sklearn.cluster import KMeans
import shutil
import numpy as np


class LDA:
    def __init__(self, proj_name):
        self.proj_name = proj_name
        self.seg_dir = proj_name + "/" + "seg"
        self.attr_dir = proj_name + "/" + "attr"
        self.tag_dict = defaultdict(int)
        self.lda = None
        self.corpus = []
        self.doc_num = None  # doc num in corpus
        self.corpus_bow = None
        self.id2word = None
        self.topic_num = 50
        self.tree = Tree()
        self.tree.create_node("Root", -1)

        self.obj_dir = self.proj_name + "/clt_topic/"
        shutil.rmtree(self.obj_dir, ignore_errors=True)
        os.mkdir(self.obj_dir)

    # 从seg文件夹中载入语料库
    def load_corpus(self, seg_dir):
        corpus = []
        seg_names = [f for f in os.listdir(seg_dir) if os.path.isfile(os.path.join(seg_dir, f))]
        for seg_name in seg_names:
            with open(os.path.join(seg_dir, seg_name), 'r') as seg_file:
                doc = []
                for sentence in seg_file:
                    sentence = sentence.strip()  # 删除前后空格，换行等空白字符
                    sentence = sentence.decode("utf-8")  # utf-8转unicode
                    words = sentence.split(u" ")
                    words = [word.strip() for word in words if len(word.strip()) > 0]
                    doc.extend(words)
                corpus.append(doc)
        return corpus

    def fit(self):
        # 载入IT停用词
        stopword = StopWord("./stopwords_it.txt")

        # 载入语料库(from seg_join/corpus.txt)
        print "reading corpus"
        corpus_name = "corpus.dat"
        if not os.path.exists(corpus_name):
            with open(self.proj_name + "/seg_join/corpus.txt", "r") as corpus_file:
                for line in corpus_file:
                    words = line.split()
                    words = [word for word in words if not stopword.is_stop_word(word)]
                    self.corpus.append(words)
            # Dumper.save(self.corpus, corpus_name)
        else:
            self.corpus = Dumper.load(corpus_name)
        self.doc_num = len(self.corpus)

        # 生成文档的词典，每个词与一个整型索引值对应
        print "creating dictionary"
        id2word_name = "id2word.dat"
        if not os.path.exists(id2word_name):
            self.id2word = corpora.Dictionary(self.corpus)
            # Dumper.save(self.id2word, id2word_name)
        else:
            self.id2word = Dumper.load(id2word_name)

        # 删除低频词
        # ignore words that appear in less than 20 documents or more than 10% documents
        # id2word.filter_extremes(no_below=20, no_above=0.1)

        # 词频统计，转化成空间向量格式
        print "tranforming doc to vector"
        corpus_bow_name = "corpus_bow.dat"
        if not os.path.exists(corpus_bow_name):
            self.corpus_bow = [self.id2word.doc2bow(doc) for doc in self.corpus]
            # Dumper.save(self.corpus_bow, corpus_bow_name)
        else:
            self.corpus_bow = Dumper.load(corpus_bow_name)

        # 训练LDA模型
        print "training lda model"
        lda_model_name = "lda_models/lda.dat"
        if not os.path.exists(lda_model_name):
            lda = LdaModel(corpus=self.corpus_bow, id2word=self.id2word, num_topics=self.topic_num, alpha='auto')
            Dumper.save(lda, lda_model_name)
        else:
            lda = Dumper.load(lda_model_name)

        # 打印识别出的主题
        topics = lda.print_topics(num_topics=self.topic_num, num_words=10)
        for topic in topics:
            print "topic %d: %s" % (topic[0], topic[1].encode("utf-8"))
        with open("topics.txt", "w") as topic_file:
            for topic in topics:
                print >> topic_file, "topic %d: %s" % (topic[0], topic[1].encode("utf-8"))
        self.lda = lda

    def tranform(self):
        # 分析每篇文章的主题分布，并保存磁盘作为特征
        corpus_vecs = []
        for i, doc_bow in enumerate(self.corpus_bow):
            print "infer topic vec: %d/%d" % (i+1, self.doc_num)
            topic_id_weights = self.lda.get_document_topics(doc_bow, minimum_probability=-1.0)
            topic_weights = [item[1] for item in topic_id_weights]
            corpus_vecs.append(topic_weights)
            obj_name = self.obj_dir + str(i + 1)
            Dumper.save(topic_weights, obj_name)

        cluster_num1 = 10
        cluster_num2 = 5
        category_offset = 0
        # 第一次聚类
        print "first clustering..."
        corpus_vecs = np.asarray(corpus_vecs)
        clt = KMeans(n_clusters=cluster_num1)
        clt.fit(corpus_vecs)

        # 第一次聚类结果写入mysql
        print "writing clustering result to mysql..."
        db = ArticleDB()
        for i in xrange(self.doc_num):
            db.execute("update %s set category1=%d where id=%d" % (self.proj_name, clt.labels_[i], i + 1))
        category_offset += cluster_num1

        # 按照第一次聚类结果，对文章分组
        clusters = [[] for i in xrange(cluster_num1)]
        for i in xrange(self.doc_num):
            clusters[clt.labels_[i]].append(i + 1)

        # 第二次聚类(分组进行)
        for i in xrange(cluster_num1):
            print "second clustering: %d/%d ..." %(i+1, cluster_num1)
            # 第二次聚类
            sub_vecs = [corpus_vecs[j - 1] for j in clusters[i]]
            clt = KMeans(n_clusters=cluster_num2)
            clt.fit(sub_vecs)

            # 第二次聚类结果写入mysql
            print "writing clustering result to mysql..."
            for j in xrange(len(clusters[i])):
                db.execute("update %s set category2=%d where id=%d" % (self.proj_name, category_offset + clt.labels_[j], clusters[i][j]))

            # 类别ID起始编码
            category_offset += cluster_num2

        db.commit()
        db.close()
        print "ok, successfully complete!"

    def predict(self, x):
            # update the LDA model with additional documents
            self.lda.update(x)
            return None

    # 统计每个标签出现的次数
    def count_tag(self, attr_dir):
        attr_names = [f for f in os.listdir(attr_dir) if os.path.isfile(os.path.join(attr_dir, f))]
        for attr_name in attr_names:
            with open(os.path.join(attr_dir, attr_name), 'r') as seg_file:
                sentences = seg_file.readlines()
                if len(sentences) > 3:
                    tags = sentences[3].strip()
                    tags = tags.split(" ")
                    for tag in tags:
                            self.tag_dict[tag] += 1
        self.tag_dict = sorted(self.tag_dict.items(), lambda x, y: cmp(x[1], y[1]), reverse=True)
        with open("tags.txt", "w") as seg_file:
            for key, value in self.tag_dict:
                print >> seg_file, "%s : %d" % (key, value)


class HierarchicalClustering:
    def __init__(self):
        pass

if __name__ == '__main__':
    lda_model = LDA(proj_name="article150801160830")
    lda_model.fit()
    lda_model.tranform()
