import csv
import json
import os

import ray
from tqdm import tqdm

num_train_shards = 64
num_val_shards = 8
ray.init()


def chunkify(l, n):
    size = len(l) // n
    start = 0
    results = []
    for i in range(n - 1):
        results.append(l[start:start + size])
        start += size
    results.append(l[start:])
    return results


def _bytes_feature(value):
    if isinstance(value, type(tf.constant(0))):
        value = value.numpy(
        )  # BytesList won't unpack a string from an EagerTensor.
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def genreate_tfexample(anno_list):
    filename = anno_list[0]['filename']
    with open(filename, 'rb') as image_file:
        image_string = image_file.read()

    image = Image.open(image_path)
    image_rgb = image.convert('RGB')
    with io.BytesIO() as output:
        image_rgb.save(output, format="JPEG")
        content = output.getvalue()

    width, height = image.size
    depth = 3

    class_ids = []
    bbox_xmins = []
    bbox_ymins = []
    bbox_xmaxs = []
    bbox_ymaxs = []
    for anno in anno_list:
        class_ids.append(anno['class_id'])
        xmin, ymin, xmax, ymax = anno['xmin'], anno['ymin'], anno[
            'xmax'], anno['ymax']
        bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax = float(
            xmin) / width, float(ymin) / height, float(xmax) / width, float(
                ymax) / height
        assert bbox_xmin <= 1 and bbox_xmin >= 0
        assert bbox_ymin <= 1 and bbox_ymin >= 0
        assert bbox_xmax <= 1 and bbox_xmax >= 0
        assert bbox_ymax <= 1 and bbox_ymax >= 0
        bbox_xmins.append(bbox_xmin)
        bbox_ymins.append(bbox_ymin)
        bbox_xmaxs.append(bbox_xmax)
        bbox_ymaxs.append(bbox_ymax)

    feature = {
        'image/height':
        tf.train.Feature(int64_list=tf.train.Int64List(value=[height])),
        'image/width':
        tf.train.Feature(int64_list=tf.train.Int64List(value=[width])),
        'image/depth':
        tf.train.Feature(int64_list=tf.train.Int64List(value=[depth])),
        'image/object/bbox/xmin':
        tf.train.Feature(float_list=tf.train.FloatList(value=bbox_xmins)),
        'image/object/bbox/ymin':
        tf.train.Feature(float_list=tf.train.FloatList(value=bbox_ymins)),
        'image/object/bbox/xmax':
        tf.train.Feature(float_list=tf.train.FloatList(value=bbox_xmaxs)),
        'image/object/bbox/ymax':
        tf.train.Feature(float_list=tf.train.FloatList(value=bbox_ymaxs)),
        'image/object/class/label':
        tf.train.Feature(int64_list=tf.train.Int64List(value=class_ids)),
        'image/encoded':
        _bytes_feature(content),
        'image/filename':
        _bytes_feature(os.path.basename(filename).encode())
    }

    return tf.train.Example(features=tf.train.Features(feature=feature))


@ray.remote
def build_single_tfrecord(chunk, path):
    name, chunk = params
    print('start to build tf records for ' + path)

    with tf.io.TFRecordWriter(path) as writer:
        for anno_list in tqdm(chunk):
            if '.DS_Store' in image_path:
                continue
            tf_example = genreate_tfexample(anno_list)
            writer.write(tf_example.SerializeToString())


def build_tf_records(annotations, shards):
    annotations_by_image = {}
    for annotation in annotations:
        if annotation['filename'] in annotations_by_image:
            annotations_by_image[annotation['filename']].append(annotation)
        else:
            annotations_by_image[annotation['filename']] = [annotation]
    chunks = chunkify(annotations_by_image.values(), shards)
    futures = [
        build_single_tfrecord.remote(anno, 'train', './train2017')
        for anno in train_annos['annotations']
    ]
    ray.get(futures)


@ray.remote
def parse_one_annotation(anno, split, dir):
    category_id = anno['category_id']
    bbox = anno['bbox']
    filename = '{}/{}.jpg'.format(dir, str(anno['image_id']).rjust(12, '0'))
    annotation = {
        'filename': filename,
        'class_id': int(anno['category_id']),
        # http://cocodataset.org/#format-data
        # bbox is in format of (x, y, width, height)
        'xmin': float(bbox[0]),
        'ymin': float(bbox[1]),
        'xmax': float(bbox[0]) + float(bbox[2]),
        'ymax': float(bbox[1]) + float(bbox[3]),
        'split': split,
    }
    return annotation


def main():
    print('Start to parse annotations.')

    with open('./annotations/instances_train2017.json') as train_json:
        train_annos = json.load(train_json)
        futures = [
            parse_one_annotation.remote(anno, 'train', './train2017')
            for anno in train_annos['annotations']
        ]
        train_annotations = ray.get(futures)
        del (train_annos)

    with open('./annotations/instances_val2017.json') as val_json:
        val_annos = json.load(val_json)
        futures = [
            parse_one_annotation.remote(anno, 'test', './val2017')
            for anno in val_annos['annotations']
        ]
        val_annotations = ray.get(futures)
        del (val_annos)

    print('Start to build TF Records.')
    build_tf_records(train_annotations, num_train_shards)
    build_tf_records(val_annotations, num_val_shards)

    print('Successfully wrote {} annotations for {} images to label file.'.
          format(all_annos, len(all_files)))


if __name__ == '__main__':
    main()